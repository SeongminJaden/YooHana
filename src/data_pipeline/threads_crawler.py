"""
Threads (threads.com) crawler using Playwright.

Reuses Instagram session for login, extracts post text from search results
by parsing DOM elements directly (no API needed).
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_DATA_DIR = _PROJECT_ROOT / "data" / "raw"
_SESSION_DIR = _PROJECT_ROOT / "data" / "browser_session"
_RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)


class ThreadsCrawler:
    """Crawl Threads posts via search, reusing Instagram session."""

    def __init__(self, headless: bool = False, slow_mo: int = 300) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Try loading Instagram session (shares auth with Threads)
        session_file = _SESSION_DIR / "state.json"
        ctx_kwargs = {
            "viewport": {"width": 430, "height": 932},
            "user_agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            "locale": "ko-KR",
            "timezone_id": "Asia/Seoul",
        }
        if session_file.exists():
            ctx_kwargs["storage_state"] = str(session_file)

        self._context = self._browser.new_context(**ctx_kwargs)
        self._page = self._context.new_page()
        self._all_collected: list[dict] = []

    def _delay(self, min_s: float = 2.0, max_s: float = 4.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _scroll_down(self, times: int = 3) -> None:
        for _ in range(times):
            self._page.evaluate("window.scrollBy(0, window.innerHeight)")
            self._delay(1.5, 3.0)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _save_json(self, records: list[dict], filename: str) -> Path:
        out_path = _RAW_DATA_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2, default=str)
        logger.info("Saved {} records -> {}", len(records), out_path)
        return out_path

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self) -> bool:
        """Navigate to Threads and verify login via Instagram session."""
        logger.info("Threads: checking login status...")
        self._page.goto("https://www.threads.com/", wait_until="domcontentloaded")
        self._delay(3, 5)

        url = self._page.url
        # If redirected to login page, need Instagram login first
        if "login" in url.lower():
            logger.info("Not logged in, attempting Instagram login...")
            return self._login_via_instagram()

        # Check if logged in by looking for navigation elements
        content = self._page.content()
        if len(content) > 10000:
            logger.info("Threads: logged in successfully")
            return True

        logger.warning("Threads: login status unclear")
        return self._login_via_instagram()

    def _login_via_instagram(self) -> bool:
        """Login to Threads via Instagram credentials."""
        username = os.getenv("INSTAGRAM_USERNAME", "")
        password = os.getenv("INSTAGRAM_PASSWORD", "")
        if not username or not password:
            logger.error("No Instagram credentials in .env")
            return False

        self._page.goto(
            "https://www.threads.com/login", wait_until="domcontentloaded"
        )
        self._delay(3, 5)

        try:
            # Look for "Instagram으로 로그인" or similar button
            ig_login = self._page.locator(
                'a:has-text("Instagram"), '
                'button:has-text("Instagram"), '
                'div[role="button"]:has-text("Instagram"), '
                'a:has-text("로그인"), '
                'button:has-text("로그인")'
            )
            if ig_login.count() > 0:
                ig_login.first.click(timeout=5000)
                self._delay(3, 5)

            # Fill login form if present
            username_input = self._page.locator(
                'input[name="username"], input[type="text"]'
            )
            if username_input.count() > 0 and username_input.first.is_visible():
                username_input.first.fill(username)
                self._delay(0.5, 1.0)

                password_input = self._page.locator(
                    'input[name="password"], input[type="password"]'
                )
                password_input.first.fill(password)
                self._delay(0.5, 1.0)

                login_btn = self._page.locator(
                    'button[type="submit"], '
                    'button:has-text("로그인"), '
                    'button:has-text("Log in")'
                )
                login_btn.first.click()
                self._delay(5, 8)

            # Dismiss popups
            for _ in range(3):
                self._dismiss_overlays()
                self._delay(1, 2)

            # Save session
            session_file = _SESSION_DIR / "state.json"
            self._context.storage_state(path=str(session_file))
            logger.info("Threads: login successful, session saved")
            return True

        except Exception as exc:
            logger.error("Threads login failed: {}", exc)
            return False

    def _dismiss_overlays(self) -> None:
        """Dismiss popups on Threads."""
        for txt in ["나중에", "Not now", "닫기", "Close", "취소"]:
            try:
                btn = self._page.locator(f'button:has-text("{txt}")')
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(timeout=2000)
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Search & Extract
    # ------------------------------------------------------------------

    def search_and_collect(
        self, keyword: str, max_posts: int = 30
    ) -> list[dict]:
        """Search Threads and collect posts from results."""
        logger.info("=== Threads: searching '{}' (max {}) ===", keyword, max_posts)

        self._page.goto(
            f"https://www.threads.com/search?q={keyword}&serp_type=default",
            wait_until="domcontentloaded",
        )
        self._delay(3, 5)

        results = []
        seen_texts = set()

        # Scroll and collect multiple rounds
        scroll_rounds = max(3, max_posts // 5)
        for s in range(scroll_rounds):
            if len(results) >= max_posts:
                break

            new_posts = self._extract_visible_posts(seen_texts)
            results.extend(new_posts)

            self._scroll_down(times=1)
            self._delay(2, 4)

            if (s + 1) % 3 == 0:
                logger.info("  '{}' scroll {}/{}, {} collected",
                            keyword, s + 1, scroll_rounds, len(results))

        # Add source info
        for post in results:
            post["source"] = f"threads:search:{keyword}"

        results = results[:max_posts]
        self._all_collected.extend(results)

        if results:
            safe_kw = re.sub(r'[^\w가-힣]', '_', keyword)
            self._save_json(results, f"threads_{safe_kw}_{self._timestamp()}.json")

        logger.info("Collected {} posts from Threads search '{}'",
                     len(results), keyword)
        return results

    def _extract_visible_posts(self, seen_texts: set) -> list[dict]:
        """Extract post text from visible Threads posts on the page."""
        posts = []

        # Threads posts use div[data-pressable-container] or article-like structures
        # Text content is in span[dir="auto"] elements
        try:
            spans = self._page.locator('span[dir="auto"]')
            total = spans.count()

            for i in range(total):
                try:
                    text = spans.nth(i).text_content(timeout=500).strip()

                    # Filter: must be substantial post text
                    if len(text) < 10:
                        continue
                    if text in seen_texts:
                        continue

                    # Skip navigation/UI text
                    skip_phrases = [
                        "좋아요", "답글", "팔로우", "팔로잉", "공유",
                        "로그인", "가입", "검색", "홈", "알림",
                        "스레드", "threads", "Threads", "더 보기",
                        "프로필", "설정", "만들기",
                    ]
                    if any(text == sp or text.startswith(sp) for sp in skip_phrases):
                        continue

                    # Skip time indicators
                    if re.match(r"^\d+[시일분초주개월년]", text):
                        continue
                    # Skip pure numbers
                    if re.match(r"^[\d,.]+$", text):
                        continue
                    # Skip usernames
                    if re.match(r"^@?\w[\w.]{1,29}$", text) and " " not in text:
                        continue

                    seen_texts.add(text)

                    # Try to find username near this text
                    username = self._find_nearby_username(spans.nth(i))

                    posts.append({
                        "url": "",
                        "media_id": "",
                        "media_type": "text",
                        "caption": text,
                        "likes": 0,
                        "comments_count": 0,
                        "views": 0,
                        "user": username,
                        "hashtags": re.findall(r"#(\w+)", text),
                        "timestamp": datetime.now().isoformat(),
                        "image_urls": [],
                        "image_descriptions": [],
                        "video_url": "",
                        "carousel_count": 0,
                        "post_time_text": "",
                        "comments": [],
                        "audio": "",
                        "platform": "threads",
                    })

                except Exception:
                    continue

        except Exception as exc:
            logger.warning("Threads extraction error: {}", exc)

        return posts

    def _find_nearby_username(self, element) -> str:
        """Try to find the username associated with a post element."""
        try:
            # Navigate up to find the post container, then look for username
            parent = element.locator("xpath=ancestor::div[contains(@style, 'padding')]")
            if parent.count() > 0:
                links = parent.first.locator("a")
                for i in range(min(links.count(), 5)):
                    href = links.nth(i).get_attribute("href", timeout=300) or ""
                    if href.startswith("/@"):
                        return href[2:].rstrip("/")
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Bulk search
    # ------------------------------------------------------------------

    def bulk_search(
        self, keywords: list[str], posts_per_keyword: int = 30
    ) -> dict[str, int]:
        """Search multiple keywords and collect posts."""
        logger.info("=" * 60)
        logger.info("THREADS BULK SEARCH: {} keywords", len(keywords))
        logger.info("=" * 60)

        stats = {}
        for kw in keywords:
            try:
                results = self.search_and_collect(kw, max_posts=posts_per_keyword)
                stats[kw] = len(results)
                self._delay(3, 5)  # Rest between searches
            except Exception as exc:
                logger.error("Threads search '{}' failed: {}", kw, exc)
                stats[kw] = 0

        total = sum(stats.values())
        logger.info("=" * 60)
        logger.info("THREADS BULK COMPLETE: {} posts from {} keywords",
                     total, len(keywords))
        logger.info("=" * 60)
        return stats

    def get_all_collected(self) -> list[dict]:
        return self._all_collected

    def close(self) -> None:
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass
        logger.info("Threads browser closed")
