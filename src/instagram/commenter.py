"""Instagram comment monitoring and auto-reply using Playwright browser automation.

Scans the authenticated user's recent posts for unreplied comments,
generates context-aware replies using the project's text generator,
and posts them via browser automation while respecting rate limits.
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
_REPLIED_IDS_FILE = _DATA_DIR / "replied_comment_ids.json"


def _load_instagram_settings() -> dict:
    """Return the ``instagram`` section from settings.yaml."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            settings = yaml.safe_load(fh)
        return settings.get("instagram", {})
    except (OSError, yaml.YAMLError):
        return {}


class TextGeneratorProtocol(Protocol):
    """Protocol that any text generator must satisfy."""

    def generate(self, prompt: str, max_new_tokens: int = 128) -> str: ...


class BrowserCommenter:
    """Monitor and reply to comments using Playwright browser automation.

    Reuses the session saved by BrowserPoster / browser_crawler so that
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

        self._comments_per_hour: int = int(rate_limits.get("comments_per_hour", 10))
        self._delay_min: float = float(rate_limits.get("delay_min", 2.0))
        self._delay_max: float = float(rate_limits.get("delay_max", 5.0))

        # Rate limiting state
        self._reply_count: int = 0
        self._window_start: datetime = datetime.now(tz=timezone.utc)

        # Replied comment tracking
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
        """Initialize browser if not already running."""
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
            logger.info("브라우저 세션 로드 (댓글 모니터링)")

        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()

        # Navigate to verify session
        self._page.goto(
            "https://www.instagram.com/", wait_until="domcontentloaded"
        )
        self._delay(2, 4)
        self._dismiss_overlays()

    def close(self) -> None:
        """Close browser and save session."""
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

    # ------------------------------------------------------------------
    # Replied-ID persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _load_replied_ids() -> set[str]:
        if not _REPLIED_IDS_FILE.exists():
            return set()
        try:
            data = json.loads(_REPLIED_IDS_FILE.read_text(encoding="utf-8"))
            return set(data)
        except (json.JSONDecodeError, OSError):
            return set()

    def _save_replied_ids(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _REPLIED_IDS_FILE.write_text(
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
        if self._reply_count >= self._comments_per_hour:
            raise RateLimitError(
                f"시간당 댓글 제한 ({self._comments_per_hour}개) 도달"
            )

    # ------------------------------------------------------------------
    # Comment retrieval (Playwright)
    # ------------------------------------------------------------------

    def _get_own_username(self) -> str:
        """Get the logged-in user's username."""
        if self._username:
            return self._username

        # Try from environment
        from dotenv import load_dotenv

        load_dotenv(_PROJECT_ROOT / ".env")
        username = os.getenv("INSTAGRAM_USERNAME", "")
        if username:
            self._username = username
            return username

        # Try from profile nav links
        try:
            profile_links = self._page.locator('a[href*="/"][role="link"]')
            for i in range(profile_links.count()):
                href = (
                    profile_links.nth(i).get_attribute("href", timeout=1000) or ""
                )
                skip = (
                    "/", "/explore/", "/reels/", "/direct/inbox/",
                    "/p/", "/reel/", "/accounts/",
                )
                if any(href.startswith(s) for s in skip if s != "/"):
                    continue
                if href == "/":
                    continue
                if href.startswith("/") and href.count("/") == 2:
                    candidate = href.strip("/")
                    if candidate and " " not in candidate and len(candidate) < 40:
                        self._username = candidate
                        return candidate
        except Exception:
            pass

        return ""

    def get_recent_post_urls(self, max_posts: int = 10) -> list[str]:
        """Get URLs of the authenticated user's recent posts."""
        self._ensure_browser()

        username = self._get_own_username()
        if not username:
            logger.error("유저네임을 확인할 수 없습니다")
            return []

        self._page.goto(
            f"https://www.instagram.com/{username}/",
            wait_until="domcontentloaded",
        )
        self._delay(2, 4)
        self._dismiss_overlays()

        # Extract post URLs from profile grid
        post_links = self._page.locator('a[href*="/p/"]')
        urls: list[str] = []
        for i in range(min(post_links.count(), max_posts)):
            try:
                href = post_links.nth(i).get_attribute("href", timeout=1000)
                if href:
                    if not href.startswith("http"):
                        href = f"https://www.instagram.com{href}"
                    urls.append(href)
            except Exception:
                continue

        logger.info("@{} 최근 게시물 {}개 발견", username, len(urls))
        return urls

    def get_comments_for_post(
        self, post_url: str, max_comments: int = 20
    ) -> list[dict[str, str]]:
        """Extract comments from a post's comments page.

        Returns
        -------
        list[dict]
            Each dict has keys: ``id``, ``username``, ``text``,
            ``post_url``, ``media_id``.
        """
        self._ensure_browser()

        match = re.search(r"(/p/[^/]+/|/reel/[^/]+/)", post_url)
        if not match:
            return []

        base = match.group(1)
        media_match = re.search(r"/(?:p|reel)/([^/]+)/", base)
        media_id_str = media_match.group(1) if media_match else ""

        comments_url = f"https://www.instagram.com{base}comments/"
        self._page.goto(comments_url, wait_until="domcontentloaded")
        self._delay(2, 4)

        comments: list[dict[str, str]] = []
        skip_texts = {
            "좋아요", "답글 달기", "번역 보기", "게시",
            "댓글을 입력하세요...", "Reply", "Like", "Translate",
        }

        try:
            spans = self._page.locator('span[dir="auto"]')
            current_username = ""
            seen: set[str] = set()
            own_username = self._get_own_username()

            for i in range(min(spans.count(), 100)):
                try:
                    el = spans.nth(i)
                    text = (el.text_content(timeout=500) or "").strip()

                    if not text or text in skip_texts or len(text) <= 2:
                        continue
                    # Skip time indicators
                    if re.match(r"^\d+[시일분초주개월년]", text):
                        continue
                    if re.match(
                        r"^\d+\s*(hour|day|min|sec|week|month|year)",
                        text,
                        re.IGNORECASE,
                    ):
                        continue

                    # Check if this span is inside a link (→ username)
                    parent = el.locator("xpath=ancestor::a[@role='link']")
                    if parent.count() > 0:
                        current_username = text.strip()
                        continue

                    # This is comment text
                    if text not in seen and current_username:
                        # Skip own comments
                        if current_username == own_username:
                            current_username = ""
                            continue

                        comment_id = (
                            f"{media_id_str}_{current_username}"
                            f"_{hash(text) % 100000}"
                        )
                        seen.add(text)
                        comments.append({
                            "id": comment_id,
                            "username": current_username,
                            "text": text,
                            "post_url": post_url,
                            "media_id": media_id_str,
                        })
                        current_username = ""

                        if len(comments) >= max_comments:
                            break
                except Exception:
                    continue

        except Exception as exc:
            logger.warning("댓글 추출 실패: {}", exc)

        logger.debug("{} 댓글 추출: {}", len(comments), post_url)
        return comments

    def get_unreplied_comments(
        self, max_posts: int = 5, max_comments: int = 20
    ) -> list[dict[str, str]]:
        """Scan recent posts and return unreplied comments."""
        self._ensure_browser()

        post_urls = self.get_recent_post_urls(max_posts=max_posts)
        unreplied: list[dict[str, str]] = []

        for url in post_urls:
            comments = self.get_comments_for_post(url, max_comments)
            for comment in comments:
                if comment["id"] not in self._replied_ids:
                    unreplied.append(comment)

        logger.info(
            "미답글 댓글 {}개 (게시물 {}개 스캔)", len(unreplied), len(post_urls)
        )
        return unreplied

    # ------------------------------------------------------------------
    # Reply posting (Playwright)
    # ------------------------------------------------------------------

    def reply_to_comment(self, comment: dict, reply_text: str) -> bool:
        """Post a reply to a comment via browser automation.

        Navigates to the post and posts a comment mentioning the user.

        Parameters
        ----------
        comment : dict
            Comment dict with ``post_url``, ``username``, ``id`` keys.
        reply_text : str
            The reply text to post.

        Returns
        -------
        bool
            True if the reply was posted successfully.
        """
        self._check_rate_limit()
        self._ensure_browser()

        post_url = comment.get("post_url", "")
        username = comment.get("username", "")
        comment_id = comment.get("id", "unknown")

        if not post_url:
            logger.error("comment에 post_url 없음")
            return False

        self._page.goto(post_url, wait_until="domcontentloaded")
        self._delay(2, 4)
        self._dismiss_overlays()

        # Prepare reply with @mention
        full_reply = f"@{username} {reply_text}" if username else reply_text

        try:
            # Find comment input
            comment_input = self._page.locator(
                'textarea[aria-label="댓글 달기..."], '
                'textarea[aria-label="Add a comment…"], '
                'textarea[placeholder="댓글 달기..."], '
                'textarea[placeholder="Add a comment…"], '
                'div[role="textbox"][contenteditable="true"]'
            )

            if comment_input.count() == 0:
                # Click comment icon to reveal input
                comment_icon = self._page.locator(
                    'svg[aria-label="댓글"], svg[aria-label="Comment"]'
                )
                if comment_icon.count() > 0:
                    comment_icon.first.click()
                    self._delay(1, 2)
                    comment_input = self._page.locator(
                        "textarea, "
                        'div[role="textbox"][contenteditable="true"]'
                    )

            if comment_input.count() == 0:
                logger.error("댓글 입력란 없음: {}", post_url)
                return False

            # Type the reply
            comment_input.first.click()
            self._delay(0.3, 0.5)
            comment_input.first.fill(full_reply)
            self._delay(0.5, 1.0)

            # Click "게시" / "Post"
            post_btn = self._page.locator(
                'button:has-text("게시"), '
                'button:has-text("Post"), '
                'div[role="button"]:has-text("게시"), '
                'div[role="button"]:has-text("Post")'
            )

            if post_btn.count() > 0 and post_btn.first.is_visible():
                post_btn.first.click()
                self._delay(2, 4)

                self._reply_count += 1
                self._replied_ids.add(comment_id)
                self._save_replied_ids()

                logger.info(
                    "답글 완료: @{} → '{}'",
                    username,
                    reply_text[:40],
                )
                return True

            logger.error("게시 버튼을 찾을 수 없음")
            return False

        except Exception as exc:
            logger.error("답글 게시 실패: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Auto-reply orchestration
    # ------------------------------------------------------------------

    def auto_reply_recent(
        self,
        max_replies: int = 5,
        max_posts: int = 5,
    ) -> int:
        """Scan recent posts and auto-reply to unreplied comments.

        Parameters
        ----------
        max_replies : int
            Maximum replies to post in this invocation.
        max_posts : int
            Number of recent posts to scan.

        Returns
        -------
        int
            Number of replies successfully posted.
        """
        self._ensure_browser()

        unreplied = self.get_unreplied_comments(max_posts=max_posts)
        if not unreplied:
            logger.info("답글할 댓글 없음")
            return 0

        replied_count = 0

        for comment in unreplied[:max_replies]:
            try:
                self._check_rate_limit()
            except RateLimitError:
                logger.warning("시간당 댓글 제한 도달 — 중단")
                break

            # Generate reply using fine-tuned model
            try:
                prompt = (
                    f"### Instruction:\n"
                    f"[팔로워 댓글] {comment['text']}\n"
                    f"이 댓글에 답글을 써줘\n\n"
                    f"### Response:\n"
                )
                reply_text = self._generator.generate(
                    prompt, max_new_tokens=128
                )

                # Clean up prefixes
                for prefix in ("하나:", "하나 :", "유하나:", "유하나 :"):
                    if reply_text.startswith(prefix):
                        reply_text = reply_text[len(prefix) :].strip()

                # Truncate at meta-text
                for stop in ("상대:", "### Instruction", "###", "\n\n\n"):
                    idx = reply_text.find(stop)
                    if idx > 0:
                        reply_text = reply_text[:idx].strip()

            except Exception as exc:
                logger.error("답글 생성 실패 ({}): {}", comment["id"], exc)
                continue

            if not reply_text:
                continue

            # Post the reply
            try:
                success = self.reply_to_comment(comment, reply_text)
                if success:
                    replied_count += 1
                    self._delay(self._delay_min, self._delay_max)
            except (InstagramError, RateLimitError) as exc:
                logger.warning("답글 실패: {}", exc)
                continue

        logger.info("자동 답글 완료: {}개 게시", replied_count)
        return replied_count
