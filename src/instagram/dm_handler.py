"""Instagram DM (Direct Message) monitoring and auto-reply using Playwright.

Scans the authenticated user's DM inbox for unread conversations,
generates context-aware replies using the project's text generator,
and sends them via browser automation while respecting rate limits.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import yaml

from src.utils.error_handler import InstagramError, RateLimitError
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"
_DATA_DIR = _PROJECT_ROOT / "data"
_SESSION_DIR = _DATA_DIR / "browser_session"
_REPLIED_DM_FILE = _DATA_DIR / "replied_dm_ids.json"
_DM_CACHE_FILE = _DATA_DIR / "dm_cache.json"


def _load_instagram_settings() -> dict:
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            settings = yaml.safe_load(fh)
        return settings.get("instagram", {})
    except (OSError, yaml.YAMLError):
        return {}


class TextGeneratorProtocol(Protocol):
    def generate(self, prompt: str, max_new_tokens: int = 128) -> str: ...


class BrowserDMHandler:
    """Monitor and reply to Instagram DMs using Playwright browser automation.

    Reuses the session saved by BrowserPoster / BrowserCommenter so that
    a separate login is not required.

    Parameters
    ----------
    text_generator : TextGeneratorProtocol
        Object with a ``generate(prompt, max_new_tokens)`` method.
    headless : bool
        Run without a visible browser window.
    slow_mo : int
        Milliseconds of delay between Playwright actions.
    """

    def __init__(
        self,
        text_generator: TextGeneratorProtocol,
        headless: bool = True,
        slow_mo: int = 500,
    ) -> None:
        self._generator = text_generator
        self._headless = headless
        self._slow_mo = slow_mo

        ig_cfg = _load_instagram_settings()
        rate_limits = ig_cfg.get("rate_limits", {})

        self._dms_per_hour: int = int(rate_limits.get("dms_per_hour", 8))
        self._delay_min: float = float(rate_limits.get("delay_min", 2.0))
        self._delay_max: float = float(rate_limits.get("delay_max", 5.0))

        # Rate limiting state
        self._reply_count: int = 0
        self._window_start: datetime = datetime.now(tz=timezone.utc)

        # Replied DM tracking
        self._replied_ids: set[str] = self._load_replied_ids()

        # Browser (lazy init)
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._username: str = ""

    # ------------------------------------------------------------------
    # Browser lifecycle
    # ------------------------------------------------------------------

    def _ensure_browser(self) -> None:
        if self._page is not None:
            return

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_kwargs: dict[str, Any] = {
            "viewport": {"width": 430, "height": 932},
            "user_agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }

        session_file = _SESSION_DIR / "state.json"
        if session_file.exists():
            context_kwargs["storage_state"] = str(session_file)
            logger.info("브라우저 세션 로드 (DM 모니터링)")

        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()

        self._page.goto(
            "https://www.instagram.com/", wait_until="domcontentloaded"
        )
        self._delay(2, 4)
        self._dismiss_overlays()

    def close(self) -> None:
        if self._context:
            try:
                _SESSION_DIR.mkdir(parents=True, exist_ok=True)
                self._context.storage_state(
                    path=str(_SESSION_DIR / "state.json")
                )
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._page = None
        self._browser = None
        self._pw = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _delay(self, min_s: float = 1.0, max_s: float = 3.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _dismiss_overlays(self) -> None:
        dismiss_texts = [
            "나중에 하기", "나중에", "Not Now", "Not now",
            "닫기", "Close", "취소", "Cancel",
            "끄기", "Turn Off",
        ]
        for txt in dismiss_texts:
            try:
                btn = self._page.locator(
                    f'button:has-text("{txt}"), '
                    f'div[role="button"]:has-text("{txt}")'
                )
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(timeout=2000)
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    def _get_own_username(self) -> str:
        if self._username:
            return self._username
        from dotenv import load_dotenv
        load_dotenv(_PROJECT_ROOT / ".env")
        username = os.getenv("INSTAGRAM_USERNAME", "")
        if username:
            self._username = username
        return username

    # ------------------------------------------------------------------
    # Replied-ID persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _load_replied_ids() -> set[str]:
        if not _REPLIED_DM_FILE.exists():
            return set()
        try:
            data = json.loads(_REPLIED_DM_FILE.read_text(encoding="utf-8"))
            return set(data)
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_replied_ids(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _REPLIED_DM_FILE.write_text(
            json.dumps(sorted(self._replied_ids), indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> None:
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._window_start).total_seconds()
        if elapsed >= 3600:
            self._reply_count = 0
            self._window_start = now
        if self._reply_count >= self._dms_per_hour:
            raise RateLimitError(
                f"시간당 DM 제한 ({self._dms_per_hour}개) 도달"
            )

    # ------------------------------------------------------------------
    # DM inbox retrieval
    # ------------------------------------------------------------------

    def get_conversations(self, max_convos: int = 15) -> list[dict[str, Any]]:
        """Get list of recent DM conversations from inbox.

        Returns
        -------
        list[dict]
            Each dict has keys: ``id``, ``username``, ``last_message``,
            ``unread``, ``url``.
        """
        self._ensure_browser()

        self._page.goto(
            "https://www.instagram.com/direct/inbox/",
            wait_until="domcontentloaded",
        )
        self._delay(3, 5)
        self._dismiss_overlays()
        self._delay(1, 2)

        conversations: list[dict[str, Any]] = []
        seen_users: set[str] = set()

        try:
            # Conversation items are links to /direct/t/{thread_id}
            thread_links = self._page.locator('a[href*="/direct/t/"]')
            count = min(thread_links.count(), max_convos * 2)

            for i in range(count):
                if len(conversations) >= max_convos:
                    break

                try:
                    link = thread_links.nth(i)
                    href = link.get_attribute("href", timeout=1000) or ""

                    # Extract thread ID
                    thread_match = re.search(r"/direct/t/(\d+)", href)
                    if not thread_match:
                        continue
                    thread_id = thread_match.group(1)

                    # Extract username and last message from the link content
                    spans = link.locator('span[dir="auto"], span')
                    username = ""
                    last_message = ""
                    texts: list[str] = []

                    for j in range(min(spans.count(), 10)):
                        try:
                            text = (spans.nth(j).text_content(timeout=500) or "").strip()
                            if text and len(text) > 0:
                                texts.append(text)
                        except Exception:
                            continue

                    # First meaningful text is usually the username
                    skip_texts = {
                        "활성 상태", "Active", "읽지 않음", "사진",
                        "동영상", "음성 메시지", "좋아요",
                    }
                    for text in texts:
                        if text in skip_texts:
                            continue
                        # Time indicators
                        if re.match(r"^\d+[시일분초주개월년]", text):
                            continue
                        if re.match(r"^\d+\s*(h|m|s|d|w)", text):
                            continue
                        if not username:
                            username = text
                        elif not last_message and text != username:
                            last_message = text
                            break

                    if not username or username in seen_users:
                        continue
                    seen_users.add(username)

                    # Check for unread indicator (blue dot or bold text)
                    is_unread = False
                    try:
                        # Unread conversations often have a blue dot or bold styling
                        unread_dot = link.locator(
                            'div[style*="background-color: rgb(0, 149, 246)"], '
                            'div[style*="background: rgb(0, 149, 246)"]'
                        )
                        if unread_dot.count() > 0:
                            is_unread = True
                    except Exception:
                        pass

                    full_url = f"https://www.instagram.com/direct/t/{thread_id}/"

                    conversations.append({
                        "id": f"dm_{thread_id}_{username}",
                        "thread_id": thread_id,
                        "username": username,
                        "last_message": last_message,
                        "unread": is_unread,
                        "url": full_url,
                    })

                except Exception:
                    continue

        except Exception as exc:
            logger.warning("DM 목록 추출 실패: {}", exc)

        logger.info("DM 대화 {}개 발견", len(conversations))
        return conversations

    def get_messages_in_thread(
        self, thread_url: str, max_messages: int = 10
    ) -> list[dict[str, str]]:
        """Read messages from a specific DM thread.

        Returns
        -------
        list[dict]
            Each dict has keys: ``sender``, ``text``, ``is_own``.
            Ordered from oldest to newest.
        """
        self._ensure_browser()

        self._page.goto(thread_url, wait_until="domcontentloaded")
        self._delay(3, 5)
        self._dismiss_overlays()

        messages: list[dict[str, str]] = []
        own_username = self._get_own_username()

        try:
            # Messages are typically in div elements with role or specific structure
            # Instagram DM messages are in div containers
            msg_containers = self._page.locator(
                'div[role="row"], '
                'div[class*="message"], '
                'div[data-testid="message-list"] > div'
            )

            # Fallback: try to find text spans in the message area
            if msg_containers.count() == 0:
                msg_containers = self._page.locator(
                    'div[role="listbox"] div[role="row"]'
                )

            # Extract text from visible message elements
            all_spans = self._page.locator(
                'div[role="row"] span[dir="auto"], '
                'div[role="listbox"] span[dir="auto"]'
            )

            seen_texts: set[str] = set()
            skip_texts = {
                "좋아요", "읽지 않음", "활성 상태", "사진 보내기",
                "메시지 보내기...", "메시지를 입력하세요", "GIF",
                "음성 메시지", "사진", "동영상", "스티커",
            }

            for i in range(min(all_spans.count(), max_messages * 3)):
                try:
                    span = all_spans.nth(i)
                    text = (span.text_content(timeout=500) or "").strip()

                    if not text or len(text) < 1:
                        continue
                    if text in skip_texts or text in seen_texts:
                        continue
                    # Skip time indicators
                    if re.match(r"^\d+[시일분초주개월년]", text):
                        continue
                    if re.match(r"^(오전|오후)\s*\d+:\d+", text):
                        continue
                    if re.match(r"^\d{1,2}:\d{2}\s*(AM|PM)?$", text, re.IGNORECASE):
                        continue
                    # Skip date headers
                    if re.match(r"^\d{4}년", text):
                        continue
                    if re.match(r"^\d+월\s*\d+일", text):
                        continue
                    # Skip usernames that appear as headers
                    if re.match(r"^@?\w[\w.]{1,29}$", text) and " " not in text:
                        continue

                    seen_texts.add(text)

                    # Determine if this is own message by checking alignment/styling
                    is_own = False
                    try:
                        parent = span.locator("xpath=ancestor::div[@role='row']")
                        if parent.count() > 0:
                            # Own messages are typically right-aligned with blue background
                            style = parent.first.get_attribute("style", timeout=300) or ""
                            class_attr = parent.first.get_attribute("class", timeout=300) or ""
                            inner_html = parent.first.inner_html(timeout=500)
                            # Blue background = own message on Instagram
                            if "3797F0" in inner_html or "0095F6" in inner_html:
                                is_own = True
                            # Check for flex-end alignment (right side = own)
                            if "flex-end" in style or "flex-end" in inner_html:
                                is_own = True
                    except Exception:
                        pass

                    messages.append({
                        "sender": own_username if is_own else "other",
                        "text": text,
                        "is_own": is_own,
                    })

                    if len(messages) >= max_messages:
                        break

                except Exception:
                    continue

        except Exception as exc:
            logger.warning("DM 메시지 읽기 실패: {}", exc)

        logger.debug("스레드에서 메시지 {}개 추출", len(messages))
        return messages

    def get_unread_conversations(
        self, max_convos: int = 10
    ) -> list[dict[str, Any]]:
        """Get conversations with unread messages.

        Also reads the latest messages from each unread thread.
        """
        self._ensure_browser()

        conversations = self.get_conversations(max_convos=max_convos)
        unread: list[dict[str, Any]] = []

        for convo in conversations:
            dm_id = convo["id"]

            # Skip already replied
            if dm_id in self._replied_ids:
                continue

            # Read messages from this thread
            messages = self.get_messages_in_thread(
                convo["url"], max_messages=5
            )
            convo["messages"] = messages

            # Find the last message from the other person
            other_messages = [m for m in messages if not m.get("is_own")]
            if other_messages:
                convo["last_other_message"] = other_messages[-1]["text"]

                # Check if last message in thread is from the other person (needs reply)
                if messages and not messages[-1].get("is_own"):
                    unread.append(convo)

            self._delay(1, 2)

        logger.info("답변 필요한 DM {}개", len(unread))
        return unread

    # ------------------------------------------------------------------
    # Sending DM replies
    # ------------------------------------------------------------------

    def send_dm_reply(self, thread_url: str, reply_text: str) -> bool:
        """Send a reply message in a DM thread.

        Parameters
        ----------
        thread_url : str
            URL of the DM thread.
        reply_text : str
            The reply text to send.

        Returns
        -------
        bool
            True if the message was sent successfully.
        """
        self._check_rate_limit()
        self._ensure_browser()

        self._page.goto(thread_url, wait_until="domcontentloaded")
        self._delay(2, 4)
        self._dismiss_overlays()

        try:
            # Find message input
            msg_input = self._page.locator(
                'textarea[placeholder="메시지 보내기..."], '
                'textarea[placeholder="Message..."], '
                'div[role="textbox"][contenteditable="true"], '
                'textarea[aria-label="메시지"], '
                'textarea[aria-label="Message"]'
            )

            if msg_input.count() == 0:
                logger.error("DM 입력란을 찾을 수 없음: {}", thread_url)
                return False

            # Click and type the message
            msg_input.first.click()
            self._delay(0.3, 0.5)
            msg_input.first.fill(reply_text)
            self._delay(0.5, 1.0)

            # Send: press Enter or click send button
            send_btn = self._page.locator(
                'button:has-text("보내기"), '
                'button:has-text("Send"), '
                'div[role="button"]:has-text("보내기")'
            )

            if send_btn.count() > 0 and send_btn.first.is_visible():
                send_btn.first.click()
            else:
                # Press Enter to send
                msg_input.first.press("Enter")

            self._delay(2, 3)

            self._reply_count += 1
            logger.info("DM 전송 완료: '{}'", reply_text[:40])
            return True

        except Exception as exc:
            logger.error("DM 전송 실패: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Auto-reply orchestration
    # ------------------------------------------------------------------

    def auto_reply_dms(
        self,
        max_replies: int = 3,
        max_convos: int = 10,
    ) -> int:
        """Scan inbox and auto-reply to unread DMs.

        Parameters
        ----------
        max_replies : int
            Maximum replies to send in this invocation.
        max_convos : int
            Number of conversations to scan.

        Returns
        -------
        int
            Number of replies successfully sent.
        """
        self._ensure_browser()

        unread = self.get_unread_conversations(max_convos=max_convos)
        if not unread:
            logger.info("답변할 DM 없음")
            return 0

        replied_count = 0

        for convo in unread[:max_replies]:
            try:
                self._check_rate_limit()
            except RateLimitError:
                logger.warning("시간당 DM 제한 도달 — 중단")
                break

            dm_id = convo["id"]
            username = convo.get("username", "")
            last_msg = convo.get("last_other_message", "")

            if not last_msg:
                continue

            # Build context from conversation history
            messages = convo.get("messages", [])
            context_lines = []
            for msg in messages[-5:]:
                sender = "나" if msg.get("is_own") else username
                context_lines.append(f"{sender}: {msg['text']}")
            conversation_context = "\n".join(context_lines)

            # Generate reply
            try:
                prompt = (
                    f"### Instruction:\n"
                    f"[DM 대화 상대: @{username}]\n"
                )
                if conversation_context:
                    prompt += f"[대화 맥락]\n{conversation_context}\n"
                prompt += (
                    f"[상대방 메시지] {last_msg}\n"
                    f"이 DM에 자연스럽게 답장을 써줘. "
                    f"친근하고 캐주얼한 말투로 짧게 답해줘.\n\n"
                    f"### Response:\n"
                )
                reply_text = self._generator.generate(
                    prompt, max_new_tokens=128
                )

                # Clean up prefixes
                for prefix in ("하나:", "하나 :", "유하나:", "유하나 :"):
                    if reply_text.startswith(prefix):
                        reply_text = reply_text[len(prefix):].strip()

                # Truncate at meta-text
                for stop in ("상대:", "### Instruction", "###", "\n\n\n"):
                    idx = reply_text.find(stop)
                    if idx > 0:
                        reply_text = reply_text[:idx].strip()

            except Exception as exc:
                logger.error("DM 답변 생성 실패 ({}): {}", dm_id, exc)
                continue

            if not reply_text:
                continue

            # Send the reply
            try:
                success = self.send_dm_reply(convo["url"], reply_text)
                if success:
                    replied_count += 1
                    self._replied_ids.add(dm_id)
                    self._save_replied_ids()

                    logger.info(
                        "DM 답변 완료: @{} → '{}'",
                        username,
                        reply_text[:40],
                    )
                    self._delay(self._delay_min, self._delay_max)
            except (InstagramError, RateLimitError) as exc:
                logger.warning("DM 답변 실패: {}", exc)
                continue

        logger.info("자동 DM 답변 완료: {}개 전송", replied_count)
        return replied_count

    # ------------------------------------------------------------------
    # Cache helpers (for web UI)
    # ------------------------------------------------------------------

    @staticmethod
    def load_dm_cache() -> list[dict]:
        if not _DM_CACHE_FILE.exists():
            return []
        try:
            return json.loads(_DM_CACHE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def save_dm_cache(dms: list[dict]) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _DM_CACHE_FILE.write_text(
            json.dumps(dms, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
