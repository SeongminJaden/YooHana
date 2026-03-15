"""
Instagram browser-based crawler using Playwright.

Automates a real Chromium browser to log in, navigate, click, scroll,
and scrape posts/reels/comments from Instagram.
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

import yaml

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_DATA_DIR = _PROJECT_ROOT / "data" / "raw"
_SESSION_DIR = _PROJECT_ROOT / "data" / "browser_session"
_PERSONA_PATH = _PROJECT_ROOT / "config" / "persona.yaml"
_RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
_SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _load_persona_keywords() -> list[str]:
    """Load persona-relevant keywords from persona.yaml."""
    try:
        with open(_PERSONA_PATH, "r", encoding="utf-8") as fh:
            persona = yaml.safe_load(fh)

        keywords = []
        # Content themes
        themes = persona.get("content_themes", {})
        for theme_list in themes.get("primary", []):
            # Extract Korean keywords from descriptions like "일상 라이프스타일 (카페, 산책, 일상)"
            keywords.extend(re.findall(r"[\uac00-\ud7a3]+", theme_list))
        for theme_list in themes.get("secondary", []):
            keywords.extend(re.findall(r"[\uac00-\ud7a3]+", theme_list))
        for season_list in themes.get("seasonal", {}).values():
            for item in season_list:
                keywords.extend(re.findall(r"[\uac00-\ud7a3]+", item))

        # Also add English equivalents for common themes
        keywords.extend([
            "cafe", "coffee", "ootd", "fashion", "style", "daily",
            "lifestyle", "seoul", "aesthetic", "mood", "vlog",
            "selfie", "outfit", "beauty", "makeup", "skincare",
        ])

        # Forbidden topics to exclude
        forbidden = persona.get("boundaries", {}).get("forbidden_topics", [])
        return keywords, forbidden
    except Exception:
        return [], []


class InstagramBrowserCrawler:
    """Crawl Instagram using a real browser via Playwright.

    Handles login, navigation, scrolling, and data extraction
    by interacting with actual page elements.
    """

    def __init__(self, headless: bool = True, slow_mo: int = 300) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = self._browser.new_context(
            viewport={"width": 430, "height": 932},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        self._page = self._context.new_page()
        self._logged_in = False
        self._all_collected: list[dict] = []

        # Load persona keywords for relevance filtering
        self._persona_keywords, self._forbidden_topics = _load_persona_keywords()
        logger.info("Persona filter loaded: {} keywords", len(self._persona_keywords))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_relevant(self, post_data: dict, strict: bool = False) -> bool:
        """Check if post matches persona themes (Korean lifestyle/fashion).

        Args:
            post_data: Post data dict.
            strict: If False (default), accept any Korean-language post.
                    If True, require keyword match (for explore/reels).
        """
        text = (post_data.get("caption", "") + " " + " ".join(post_data.get("hashtags", []))).lower()

        if not text.strip():
            return False

        # Check forbidden topics
        for forbidden in self._forbidden_topics:
            if forbidden in text:
                logger.debug("Filtered out (forbidden topic '{}'): {}", forbidden, text[:60])
                return False

        # Non-strict mode: accept any post with Korean text
        if not strict:
            return True

        # Strict mode: check persona keywords
        if self._persona_keywords:
            for kw in self._persona_keywords:
                if kw.lower() in text:
                    return True
            # Korean text is still a positive signal in strict mode
            if re.search(r"[\uac00-\ud7a3]", text):
                return True
            return False

        return True

    def _dismiss_overlays(self) -> None:
        """Dismiss any overlay popups (save login, notifications, cookie, app banner)."""
        # Order matters: prefer "나중에"/"Not Now" over "저장"/"Save" to avoid navigation
        dismiss_texts = [
            "나중에 하기", "나중에", "Not Now", "Not now",
            "닫기", "Close",
            "취소", "Cancel",
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
                    logger.debug("Dismissed overlay: '{}'", txt)
                    return  # one overlay at a time
            except Exception:
                continue

        # Also dismiss "앱 사용" bottom banner
        try:
            app_banner = self._page.locator('a:has-text("앱 사용"), button:has-text("앱 사용")')
            close_btn = self._page.locator('button[aria-label="닫기"], svg[aria-label="닫기"]')
            if app_banner.count() > 0:
                # Find and click the X/close button near the app banner
                if close_btn.count() > 0:
                    close_btn.last.click(timeout=2000)
                    time.sleep(0.3)
            # Also try dismissing the bottom "앱에서 열기" bar by pressing Escape
        except Exception:
            pass

    def _delay(self, min_s: float = 2.0, max_s: float = 5.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _scroll_down(self, times: int = 3) -> None:
        for _ in range(times):
            self._page.evaluate("window.scrollBy(0, window.innerHeight)")
            self._delay(1.0, 2.5)

    def _save_json(self, records: list[dict], filename: str) -> Path:
        out_path = _RAW_DATA_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2, default=str)
        logger.info("Saved {} records -> {}", len(records), out_path)
        return out_path

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def screenshot(self, name: str = "debug") -> str:
        path = str(_RAW_DATA_DIR / f"screenshot_{name}_{self._timestamp()}.png")
        self._page.screenshot(path=path)
        logger.info("Screenshot saved: {}", path)
        return path

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, username: str = None, password: str = None) -> bool:
        """Log into Instagram via the browser."""
        if not username or not password:
            from dotenv import load_dotenv
            load_dotenv(_PROJECT_ROOT / ".env")
            username = os.getenv("INSTAGRAM_USERNAME", "")
            password = os.getenv("INSTAGRAM_PASSWORD", "")

        if not username or not password:
            logger.error("No credentials provided")
            return False

        # Try loading saved session
        session_file = _SESSION_DIR / "state.json"
        if session_file.exists():
            try:
                self._context.close()
                self._context = self._browser.new_context(
                    storage_state=str(session_file),
                    viewport={"width": 430, "height": 932},
                    user_agent=(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                        "Version/17.0 Mobile/15E148 Safari/604.1"
                    ),
                    locale="ko-KR",
                    timezone_id="Asia/Seoul",
                )
                self._page = self._context.new_page()
                self._page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                self._delay(3, 5)

                # Check if we're logged in
                if self._is_logged_in():
                    self._logged_in = True
                    logger.info("Restored saved session - logged in")
                    return True
                else:
                    logger.info("Saved session expired, doing fresh login...")
            except Exception:
                logger.info("Failed to restore session, doing fresh login...")

        # Fresh login
        logger.info("Navigating to Instagram login...")
        self._page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        self._delay(3, 5)

        # Dismiss cookie dialog if present
        try:
            cookie_btn = self._page.locator("button:has-text('Allow'), button:has-text('허용'), button:has-text('Accept')")
            if cookie_btn.count() > 0:
                cookie_btn.first.click()
                self._delay(1, 2)
        except Exception:
            pass

        # Fill credentials
        logger.info("Entering credentials...")
        try:
            username_input = self._page.locator(
                'input[name="username"], '
                'input[aria-label="사용자 이름, 이메일 주소 또는 휴대폰 번호"], '
                'input[aria-label*="username"], '
                'input[type="text"]'
            ).first
            username_input.wait_for(state="visible", timeout=10000)
            username_input.fill(username)
            self._delay(0.5, 1.0)

            password_input = self._page.locator(
                'input[name="password"], '
                'input[aria-label="비밀번호"], '
                'input[aria-label*="password"], '
                'input[type="password"]'
            ).first
            password_input.fill(password)
            self._delay(0.5, 1.0)

            # Click login button (try multiple selectors for Korean/English)
            login_btn = self._page.locator(
                'button[type="submit"], '
                'button:has-text("로그인"), '
                'button:has-text("Log in"), '
                'div[role="button"]:has-text("로그인"), '
                'div[role="button"]:has-text("Log in")'
            )
            login_btn.first.click()
            self._delay(5, 8)

        except Exception as exc:
            logger.error("Failed to fill login form: {}", exc)
            self.screenshot("login_error")
            return False

        # Handle various post-login popups (save info, notifications, etc.)
        for _ in range(3):
            self._delay(1.0, 2.0)
            self._dismiss_overlays()

        # Verify login
        if self._is_logged_in():
            self._logged_in = True
            # Save session
            self._context.storage_state(path=str(session_file))
            logger.info("Login successful! Session saved.")
            return True
        else:
            logger.error("Login verification failed")
            self.screenshot("login_failed")
            return False

    def _is_logged_in(self) -> bool:
        """Check if currently logged into Instagram."""
        try:
            url = self._page.url
            # If we're on a login page, we're not logged in
            if "/accounts/login" in url:
                return False

            # Challenge page may still mean we're partially logged in
            if "/challenge" in url:
                logger.info("Challenge page detected at: {}", url)
                return False

            # Look for nav elements that only appear when logged in
            selectors = [
                'svg[aria-label="홈"]',
                'svg[aria-label="Home"]',
                'a[href="/"]',
                'svg[aria-label="검색"]',
                'svg[aria-label="Search"]',
                'a[href="/explore/"]',
                'span[aria-label="프로필"]',
                'span[aria-label="Profile"]',
            ]
            for sel in selectors:
                if self._page.locator(sel).count() > 0:
                    return True

            # Fallback: check if the page body has logged-in indicators
            body = self._page.content()
            if '"viewer"' in body or '"viewerId"' in body:
                return True

            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def go_to_user(self, username: str) -> bool:
        """Navigate to a user's profile page."""
        self._page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
        self._delay(3, 5)
        self._dismiss_overlays()
        # Check if user exists
        if "페이지를 사용할 수 없습니다" in self._page.content() or "Page Not Found" in self._page.content():
            logger.warning("User @{} not found", username)
            return False
        return True

    def go_to_hashtag(self, hashtag: str) -> bool:
        """Navigate to a hashtag page."""
        tag = hashtag.lstrip("#")
        self._page.goto(f"https://www.instagram.com/explore/tags/{tag}/", wait_until="domcontentloaded")
        self._delay(3, 5)
        self._dismiss_overlays()
        return True

    def go_to_explore(self) -> bool:
        """Navigate to the explore page."""
        self._page.goto("https://www.instagram.com/explore/", wait_until="domcontentloaded")
        self._delay(3, 5)
        self._dismiss_overlays()
        return True

    def go_to_reels(self) -> bool:
        """Navigate to the reels page."""
        self._page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
        self._delay(3, 5)
        self._dismiss_overlays()
        return True

    # ------------------------------------------------------------------
    # Data extraction from post/reel detail page
    # ------------------------------------------------------------------

    def _extract_post_via_embed(self, post_url: str) -> dict[str, Any] | None:
        """Extract post data via Instagram embed page (works in headless)."""
        # Convert /p/XXXX/ or /reel/XXXX/ to embed URL
        match = re.search(r"(/p/[^/]+/|/reel/[^/]+/)", post_url)
        if not match:
            return None

        embed_url = f"https://www.instagram.com{match.group(1)}embed/"
        try:
            self._page.goto(embed_url, wait_until="domcontentloaded")
            time.sleep(2)

            html = self._page.content()
            if len(html) < 200:
                return None

            data: dict[str, Any] = {
                "url": post_url,
                "media_id": "",
                "media_type": "reel" if "/reel/" in post_url else "photo",
                "caption": "",
                "likes": 0,
                "comments_count": 0,
                "views": 0,
                "user": "",
                "timestamp": datetime.now().isoformat(),
                "post_time_text": "",
                "hashtags": [],
                "comments": [],
                "audio": "",
                "image_urls": [],
                "image_descriptions": [],
                "video_url": "",
                "carousel_count": 1,
            }

            mid = re.search(r"/p/([^/]+)/|/reel/([^/]+)/", post_url)
            if mid:
                data["media_id"] = mid.group(1) or mid.group(2)

            # Username from embed
            try:
                user_el = self._page.locator("a.e1e1d span, .UsernameText, a[href*='instagram.com/'] span")
                if user_el.count() > 0:
                    data["user"] = user_el.first.text_content(timeout=2000).strip().replace("@", "")
            except Exception:
                pass

            # Try simpler selectors for username
            if not data["user"]:
                try:
                    # Embed pages have a header with username link
                    header_links = self._page.locator("header a")
                    for i in range(header_links.count()):
                        href = header_links.nth(i).get_attribute("href", timeout=1000) or ""
                        text = header_links.nth(i).text_content(timeout=1000).strip()
                        if "instagram.com/" in href and text and len(text) < 30:
                            data["user"] = text.replace("@", "")
                            break
                except Exception:
                    pass

            # Caption from embed page
            try:
                # Embed pages wrap caption in a div with class containing "Caption"
                caption_el = self._page.locator(
                    'div[class*="Caption"] span, '
                    'div[class*="caption"] span, '
                    '.Caption span'
                )
                candidates = []
                for i in range(min(caption_el.count(), 10)):
                    text = caption_el.nth(i).text_content(timeout=1000).strip()
                    if len(text) > 5:
                        candidates.append(text)
                if candidates:
                    data["caption"] = max(candidates, key=len)
            except Exception:
                pass

            # Fallback: any long text span in embed
            if not data["caption"]:
                try:
                    spans = self._page.locator("span")
                    candidates = []
                    for i in range(min(spans.count(), 40)):
                        text = spans.nth(i).text_content(timeout=500).strip()
                        if (len(text) > 20
                            and not re.match(r"^@?\w[\w.]+$", text)
                            and "View" not in text
                            and "로그인" not in text):
                            candidates.append(text)
                    if candidates:
                        data["caption"] = max(candidates, key=len)
                except Exception:
                    pass

            # Extract hashtags from caption
            if data["caption"]:
                data["hashtags"] = re.findall(r"#(\w+)", data["caption"])

            # Image URLs from embed
            try:
                imgs = self._page.locator("img")
                for i in range(min(imgs.count(), 10)):
                    src = imgs.nth(i).get_attribute("src", timeout=500) or ""
                    if "scontent" in src or "instagram" in src:
                        data["image_urls"].append(src)
            except Exception:
                pass

            if data["caption"]:
                logger.debug("  Embed caption ({}ch): {}", len(data["caption"]), data["caption"][:60])
                return data

            return None
        except Exception as exc:
            logger.debug("  Embed extraction failed: {}", exc)
            return None

    def _extract_post_data(self, url: str = None) -> dict[str, Any]:
        """Extract data from a post/reel detail page (already navigated to)."""
        self._dismiss_overlays()

        # Wait for content to settle
        try:
            self._page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        data = {
            "url": url or self._page.url,
            "media_id": "",
            "media_type": "photo",
            "caption": "",
            "likes": 0,
            "comments_count": 0,
            "views": 0,
            "user": "",
            "timestamp": "",
            "post_time_text": "",
            "hashtags": [],
            "comments": [],
            "audio": "",
            "image_urls": [],
            "image_descriptions": [],
            "video_url": "",
            "carousel_count": 1,
        }

        try:
            page_url = self._page.url

            # Media ID from URL
            match = re.search(r"/p/([^/]+)/|/reel/([^/]+)/", page_url)
            if match:
                data["media_id"] = match.group(1) or match.group(2)

            # Detect type
            if "/reel/" in page_url:
                data["media_type"] = "reel"

            # Try expanding "더 보기" (see more) for full caption
            try:
                more_btn = self._page.locator(
                    'button:has-text("더 보기"), '
                    'span:has-text("더 보기"), '
                    'button:has-text("more"), '
                    'div[role="button"]:has-text("더 보기")'
                )
                if more_btn.count() > 0:
                    more_btn.first.click(timeout=2000)
                    time.sleep(0.5)
            except Exception:
                pass

            # Username: find the first a[role="link"] that links to a user profile
            try:
                user_links = self._page.locator('a[role="link"]')
                for i in range(user_links.count()):
                    href = user_links.nth(i).get_attribute("href", timeout=1000) or ""
                    # Skip nav links (/, /explore/, /reels/, /direct/, own profile)
                    if href in ("/", "/explore/", "/reels/", "/direct/inbox/"):
                        continue
                    if href.startswith("/") and not href.startswith("/p/") and not href.startswith("/reel/"):
                        text = user_links.nth(i).text_content(timeout=1000) or ""
                        text = text.strip()
                        # Username pattern: short, no spaces, alphanumeric+dots+underscores
                        if text and len(text) < 40 and " " not in text and text not in ("돌아가기", "홈", "탐색 탭", "릴스", "메시지"):
                            data["user"] = text.replace("@", "")
                            break
            except Exception:
                pass

            # ── Caption extraction (multiple strategies) ──

            # Strategy 1: h1 tags (Instagram uses h1 for caption text)
            try:
                h1s = self._page.locator("h1")
                for i in range(h1s.count()):
                    text = h1s.nth(i).text_content(timeout=2000) or ""
                    text = text.strip()
                    skip_h1 = {"게시물", "릴스", "Post", "Reel"}
                    if (text and text not in skip_h1 and len(text) > 3
                        and not re.match(r"^@?\w[\w.]+$", text)):
                        data["caption"] = text
                        break
            except Exception:
                pass

            # Strategy 2: span[dir="auto"] (common Instagram pattern)
            if not data["caption"]:
                try:
                    spans = self._page.locator('span[dir="auto"]')
                    candidates = []
                    for i in range(min(spans.count(), 30)):
                        text = spans.nth(i).text_content(timeout=1000) or ""
                        text = text.strip()
                        if (len(text) > 10
                            and not re.match(r"^@?\w[\w.]+$", text)
                            and not re.match(r"^\d+[시일분초주개월년]", text)
                            and text not in ("댓글 달기", "좋아요", "공유하기", "저장")):
                            candidates.append(text)

                    if candidates:
                        best = max(candidates, key=len)
                        data["caption"] = best.replace("... 더 보기", "").replace("더 보기", "").strip()
                except Exception:
                    pass

            # Strategy 3: meta og:description (reliable fallback)
            if not data["caption"]:
                try:
                    meta = self._page.locator('meta[property="og:description"]')
                    if meta.count() > 0:
                        desc = meta.first.get_attribute("content", timeout=2000) or ""
                        # Format: "N Likes, N Comments - @user on Instagram: "caption""
                        caption_match = re.search(
                            r'(?:Instagram|인스타그램)[:\s]*["\u201c](.+?)["\u201d]',
                            desc,
                        )
                        if caption_match:
                            data["caption"] = caption_match.group(1).strip()
                        elif ":" in desc:
                            # Try after the last colon
                            parts = desc.split(":")
                            candidate = parts[-1].strip().strip('"').strip('\u201c\u201d').strip()
                            if len(candidate) > 10:
                                data["caption"] = candidate
                except Exception:
                    pass

            # Strategy 4: meta description (another fallback)
            if not data["caption"]:
                try:
                    meta = self._page.locator('meta[name="description"]')
                    if meta.count() > 0:
                        desc = meta.first.get_attribute("content", timeout=2000) or ""
                        caption_match = re.search(
                            r'(?:Instagram|인스타그램)[:\s]*["\u201c](.+?)["\u201d]',
                            desc,
                        )
                        if caption_match:
                            data["caption"] = caption_match.group(1).strip()
                except Exception:
                    pass

            # Strategy 5: article or div with long text content
            if not data["caption"]:
                try:
                    articles = self._page.locator("article")
                    if articles.count() > 0:
                        spans = articles.first.locator("span")
                        candidates = []
                        for i in range(min(spans.count(), 40)):
                            text = spans.nth(i).text_content(timeout=500) or ""
                            text = text.strip()
                            if (len(text) > 15
                                and not re.match(r"^@?\w[\w.]+$", text)
                                and not re.match(r"^\d+", text)
                                and text not in ("댓글 달기", "좋아요", "공유하기", "저장", "팔로우", "팔로잉")):
                                candidates.append(text)
                        if candidates:
                            data["caption"] = max(candidates, key=len)
                except Exception:
                    pass

            if data["caption"]:
                logger.debug("  Caption found ({}ch): {}",
                             len(data["caption"]), data["caption"][:60])

            # Likes/Views: parse from section text content
            try:
                sections = self._page.locator("section")
                for i in range(sections.count()):
                    sec_text = sections.nth(i).text_content(timeout=2000) or ""
                    # Korean format: "좋아요10.3만" or "좋아요 1,234개"
                    like_match = re.search(r"좋아요\s*([\d,.]+)\s*(만|천)?", sec_text)
                    if like_match:
                        num_str = like_match.group(1).replace(",", "")
                        multiplier = {"만": 10000, "천": 1000}.get(like_match.group(2), 1)
                        try:
                            data["likes"] = int(float(num_str) * multiplier)
                        except ValueError:
                            pass

                    # English format: "1,234 likes"
                    if not data["likes"]:
                        like_match2 = re.search(r"([\d,]+)\s*likes?", sec_text, re.IGNORECASE)
                        if like_match2:
                            data["likes"] = int(like_match2.group(1).replace(",", ""))

                    # Views: "조회 10.3만" or views
                    view_match = re.search(r"조회\s*([\d,.]+)\s*(만|천)?", sec_text)
                    if view_match:
                        num_str = view_match.group(1).replace(",", "")
                        multiplier = {"만": 10000, "천": 1000}.get(view_match.group(2), 1)
                        try:
                            data["views"] = int(float(num_str) * multiplier)
                        except ValueError:
                            pass
            except Exception:
                pass

            # Comments count: "댓글 N개 모두 보기" or link to comments
            try:
                comment_link = self._page.locator('a[href*="/comments/"]')
                if comment_link.count() > 0:
                    text = comment_link.first.text_content(timeout=2000) or ""
                    nums = re.findall(r"[\d,]+", text)
                    if nums:
                        data["comments_count"] = int(nums[0].replace(",", ""))

                if not data["comments_count"]:
                    spans = self._page.locator('span[dir="auto"]')
                    for i in range(spans.count()):
                        text = spans.nth(i).text_content(timeout=500) or ""
                        match = re.search(r"댓글\s*([\d,]+)개", text)
                        if match:
                            data["comments_count"] = int(match.group(1).replace(",", ""))
                            break
            except Exception:
                pass

            # Post time: "N시간 전", "N일 전", etc.
            try:
                spans = self._page.locator('span[dir="auto"]')
                for i in range(spans.count()):
                    text = (spans.nth(i).text_content(timeout=500) or "").strip()
                    if re.match(r"^\d+[시일분초주개월년]", text) or re.match(r"^\d+\s*(hour|day|minute|week|month|year)", text, re.IGNORECASE):
                        data["post_time_text"] = text
                        break
            except Exception:
                pass

            # Audio info (for reels)
            try:
                audio_link = self._page.locator('a[href*="/reels/audio/"]')
                if audio_link.count() > 0:
                    data["audio"] = audio_link.first.text_content(timeout=2000).strip()
            except Exception:
                pass

            # Extract hashtags from caption
            if data["caption"]:
                data["hashtags"] = re.findall(r"#(\w+)", data["caption"])

            # Extract media URLs and AI-generated image descriptions
            try:
                imgs = self._page.locator("img")
                for i in range(min(imgs.count(), 20)):
                    try:
                        src = imgs.nth(i).get_attribute("src", timeout=500) or ""
                        alt = imgs.nth(i).get_attribute("alt", timeout=500) or ""
                        # Only CDN images (skip profile pics, icons)
                        if "scontent" in src and "프로필 사진" not in alt and "profile" not in alt.lower():
                            data["image_urls"].append(src)
                            if alt and ("May be" in alt or "사진" in alt or len(alt) > 30):
                                data["image_descriptions"].append(alt)
                    except Exception:
                        continue
            except Exception:
                pass

            # Extract video URL
            try:
                videos = self._page.locator("video")
                if videos.count() > 0:
                    data["media_type"] = "reel" if "/reel/" in page_url else "video"
                    src = videos.first.get_attribute("src", timeout=2000) or ""
                    if src:
                        data["video_url"] = src
            except Exception:
                pass

            # Detect carousel (multiple images)
            try:
                next_btn = self._page.locator(
                    'button[aria-label*="다음"], button[aria-label*="Next"]'
                )
                if next_btn.count() > 0:
                    # Click through carousel to collect all images
                    seen_urls = set(data["image_urls"])
                    for _ in range(10):  # max 10 slides
                        try:
                            next_btn.first.click(timeout=2000)
                            time.sleep(0.8)
                            imgs = self._page.locator("img")
                            for j in range(min(imgs.count(), 20)):
                                try:
                                    src = imgs.nth(j).get_attribute("src", timeout=300) or ""
                                    alt = imgs.nth(j).get_attribute("alt", timeout=300) or ""
                                    if ("scontent" in src
                                        and src not in seen_urls
                                        and "프로필 사진" not in alt
                                        and "profile" not in alt.lower()):
                                        data["image_urls"].append(src)
                                        seen_urls.add(src)
                                        if alt and ("May be" in alt or len(alt) > 30):
                                            data["image_descriptions"].append(alt)
                                except Exception:
                                    continue
                        except Exception:
                            break  # no more next button
                    data["carousel_count"] = len(data["image_urls"])
            except Exception:
                pass

            data["timestamp"] = datetime.now().isoformat()

        except Exception as exc:
            logger.warning("Error extracting post data: {}", exc)

        return data

    def _extract_comments(self, max_comments: int = 10) -> list[dict]:
        """Extract comments by navigating directly to the comments URL."""
        comments = []
        try:
            original_url = self._page.url

            # Build comments URL from post URL
            # /p/XXXX/ or /reel/XXXX/ -> /p/XXXX/comments/
            comments_url = None
            match = re.search(r"(/p/[^/]+/|/reel/[^/]+/)", original_url)
            if match:
                base = match.group(1)
                comments_url = f"https://www.instagram.com{base}comments/"

            if not comments_url:
                return comments

            # Navigate directly to comments page
            self._page.goto(comments_url, wait_until="domcontentloaded")
            self._delay(2, 4)

            # On comments page, extract comment texts
            spans = self._page.locator('span[dir="auto"]')
            seen = set()
            skip_texts = {"좋아요", "답글 달기", "번역 보기", "게시", "댓글을 입력하세요..."}

            for i in range(min(spans.count(), 50)):
                try:
                    text = (spans.nth(i).text_content(timeout=500) or "").strip()
                    # Filter: skip short texts, time indicators, usernames
                    if (text and len(text) > 5
                        and text not in seen
                        and text not in skip_texts
                        and not text.startswith("댓글")
                        and not re.match(r"^\d+[시일분초주개월년]", text)
                        and not re.match(r"^\d+\s*(hour|day|min|sec|week|month|year)", text, re.IGNORECASE)):
                        seen.add(text)
                        comments.append({"text": text})
                        if len(comments) >= max_comments:
                            break
                except Exception:
                    continue

            # Go back to post page
            self._page.goto(original_url, wait_until="domcontentloaded")
            self._delay(1, 2)

        except Exception as exc:
            logger.debug("Comment extraction error: {}", exc)

        return comments

    # ------------------------------------------------------------------
    # Grid scraping (user profile / hashtag / explore)
    # ------------------------------------------------------------------

    def _collect_grid_links(self, max_posts: int = 30) -> list[str]:
        """Collect post/reel links from a grid page (profile, hashtag, explore)."""
        links = set()

        # Initial collection
        self._collect_visible_links(links)

        # Scroll and collect more
        scroll_count = 0
        max_scrolls = max_posts // 4 + 3

        while len(links) < max_posts and scroll_count < max_scrolls:
            self._scroll_down(times=1)
            new_count = self._collect_visible_links(links)
            scroll_count += 1

            if new_count == 0:
                # No new links found, might be at the bottom
                self._delay(1, 2)
                self._collect_visible_links(links)
                break

            if scroll_count % 5 == 0:
                logger.info("  Scrolling... {} links found so far", len(links))

        result = list(links)[:max_posts]
        logger.info("Collected {} post links from grid", len(result))
        return result

    def _collect_visible_links(self, links: set) -> int:
        """Collect visible post/reel links on current viewport."""
        before = len(links)
        try:
            anchors = self._page.locator('a[href*="/p/"], a[href*="/reel/"]')
            for i in range(anchors.count()):
                try:
                    href = anchors.nth(i).get_attribute("href", timeout=1000)
                    if href and ("/p/" in href or "/reel/" in href):
                        if not href.startswith("http"):
                            href = f"https://www.instagram.com{href}"
                        # Remove query params (?q=...) that cause HTTP errors
                        href = href.split("?")[0]
                        # Ensure trailing slash
                        if not href.endswith("/"):
                            href += "/"
                        links.add(href)
                except Exception:
                    continue
        except Exception:
            pass
        return len(links) - before

    # ------------------------------------------------------------------
    # High-level crawl methods
    # ------------------------------------------------------------------

    def crawl_user(
        self,
        username: str,
        max_posts: int = 30,
    ) -> list[dict]:
        """Crawl posts and reels from a user's profile."""
        logger.info("=== Crawling @{} (max {} posts) ===", username, max_posts)

        if not self.go_to_user(username):
            return []

        # Get follower count
        followers = 0
        try:
            meta = self._page.locator('meta[name="description"]')
            if meta.count() > 0:
                desc = meta.first.get_attribute("content") or ""
                nums = re.findall(r"([\d,.]+[KkMm]?)\s*Followers", desc)
                if nums:
                    followers = self._parse_count(nums[0])
        except Exception:
            pass

        # Collect post links
        links = self._collect_grid_links(max_posts)

        # Visit each post and extract data
        results = []
        for i, link in enumerate(links):
            try:
                self._page.goto(link, wait_until="domcontentloaded")
                self._delay(2, 4)

                post_data = self._extract_post_data(link)
                post_data["source"] = f"@{username}"
                post_data["user"] = username
                post_data["user_followers"] = followers

                if post_data["caption"] and self._is_relevant(post_data):
                    results.append(post_data)

                if (i + 1) % 10 == 0:
                    logger.info("  Progress: {}/{} posts from @{}", i + 1, len(links), username)

            except Exception as exc:
                logger.warning("  Failed to extract post {}: {}", link, exc)
                continue

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"user_{username}_{self._timestamp()}.json")
        logger.info("Collected {} posts from @{}", len(results), username)

        return results

    def crawl_user_reels(self, username: str, max_reels: int = 20) -> list[dict]:
        """Crawl only reels from a user's profile."""
        logger.info("=== Crawling reels from @{} ===", username)

        self._page.goto(f"https://www.instagram.com/{username}/reels/", wait_until="domcontentloaded")
        self._delay(3, 5)

        links = self._collect_grid_links(max_reels)
        results = []

        for link in links:
            try:
                self._page.goto(link, wait_until="domcontentloaded")
                self._delay(2, 4)
                post_data = self._extract_post_data(link)
                post_data["media_type"] = "reel"
                post_data["source"] = f"@{username}/reels"
                if post_data["caption"] and self._is_relevant(post_data):
                    results.append(post_data)
            except Exception as exc:
                logger.warning("Failed to extract reel: {}", exc)

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"reels_{username}_{self._timestamp()}.json")
        logger.info("Collected {} reels from @{}", len(results), username)
        return results

    def crawl_hashtag_intercept(self, hashtag: str, max_posts: int = 30) -> list[dict]:
        """Crawl posts from a hashtag page by intercepting API responses.

        Instead of clicking individual posts (which triggers rate limits),
        this method captures Instagram's internal API/GraphQL responses
        that contain full post data including captions.
        """
        tag = hashtag.lstrip("#")
        logger.info("=== Crawling #{} via intercept (max {} posts) ===", tag, max_posts)

        captured_posts: list[dict] = []

        def _handle_response(response):
            """Capture Instagram API responses containing post data."""
            url = response.url
            # Instagram internal API endpoints that return post data
            api_patterns = [
                "/api/v1/tags/",
                "/api/v1/feed/tag/",
                "graphql/query",
                "/api/v1/media/",
                "/api/v1/feed/",
            ]
            if not any(p in url for p in api_patterns):
                return
            if response.status != 200:
                return

            try:
                body = response.json()
            except Exception:
                return

            # Extract posts from various API response formats
            posts = self._parse_api_response(body, tag)
            if posts:
                captured_posts.extend(posts)
                logger.debug("  Intercepted {} posts from API (total: {})",
                             len(posts), len(captured_posts))

        # Set up response listener
        self._page.on("response", _handle_response)

        try:
            # Navigate to hashtag page (triggers API calls)
            self.go_to_hashtag(tag)
            self._delay(3, 5)

            # Scroll to trigger more API calls
            scroll_rounds = max(2, max_posts // 9)
            for s in range(scroll_rounds):
                if len(captured_posts) >= max_posts:
                    break
                self._scroll_down(times=2)
                self._delay(2, 4)
                if (s + 1) % 3 == 0:
                    logger.info("  #{} scrolling... {} posts captured",
                                tag, len(captured_posts))
        finally:
            # Remove listener
            self._page.remove_listener("response", _handle_response)

        # Deduplicate by media_id
        seen_ids = set()
        results = []
        for p in captured_posts:
            mid = p.get("media_id", "")
            if mid and mid in seen_ids:
                continue
            if mid:
                seen_ids.add(mid)
            if p.get("caption") and self._is_relevant(p):
                p["source"] = f"#{tag}"
                results.append(p)

        results = results[:max_posts]
        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"hashtag_{tag}_{self._timestamp()}.json")
        logger.info("Collected {} posts from #{} (intercepted)", len(results), tag)
        return results

    def _parse_api_response(self, body: dict, source: str = "") -> list[dict]:
        """Parse Instagram API/GraphQL response to extract post data."""
        posts = []

        # Strategy 1: GraphQL hashtag response
        # data.hashtag.edge_hashtag_to_media.edges[].node
        try:
            edges = (body.get("data", {})
                     .get("hashtag", {})
                     .get("edge_hashtag_to_media", {})
                     .get("edges", []))
            for edge in edges:
                node = edge.get("node", {})
                post = self._parse_graphql_node(node)
                if post:
                    posts.append(post)
            if posts:
                return posts
        except Exception:
            pass

        # Strategy 2: v1 API tag feed
        # sections[].layout_content.medias[].media
        try:
            sections = body.get("sections", [])
            for section in sections:
                medias = (section.get("layout_content", {})
                          .get("medias", []))
                for media_wrap in medias:
                    media = media_wrap.get("media", {})
                    post = self._parse_v1_media(media)
                    if post:
                        posts.append(post)
            if posts:
                return posts
        except Exception:
            pass

        # Strategy 3: ranked_items or items array
        for key in ("ranked_items", "items", "media"):
            try:
                items = body.get(key, [])
                if isinstance(items, list):
                    for item in items:
                        post = self._parse_v1_media(item)
                        if post:
                            posts.append(post)
                if posts:
                    return posts
            except Exception:
                pass

        # Strategy 4: xdt_fbsearch / xdt_api (newer Instagram GraphQL format)
        # edges[].node.__typename == "XDTTopSerpMediaGridUnit"
        # edges[].node.items[] contains media dicts
        try:
            data = body.get("data", {})
            for key, value in data.items():
                if not isinstance(value, dict):
                    continue
                edges = value.get("edges", [])
                for edge in edges:
                    node = edge.get("node", {})
                    # XDTTopSerpMediaGridUnit has items[]
                    items = node.get("items", [])
                    if items:
                        for item in items:
                            post = self._parse_v1_media(item)
                            if post:
                                posts.append(post)
                    else:
                        # Node itself might be a media
                        post = self._parse_v1_media(node)
                        if post:
                            posts.append(post)

                # Also check sections/items directly on value
                sections = value.get("sections", [])
                for section in sections:
                    medias = (section.get("layout_content", {})
                              .get("medias", []))
                    for media_wrap in medias:
                        media = media_wrap.get("media", {})
                        post = self._parse_v1_media(media)
                        if post:
                            posts.append(post)
                items_direct = value.get("items", [])
                if isinstance(items_direct, list):
                    for item in items_direct:
                        post = self._parse_v1_media(item)
                        if post:
                            posts.append(post)

            if posts:
                return posts
        except Exception:
            pass

        return posts

    def _parse_graphql_node(self, node: dict) -> dict | None:
        """Parse a GraphQL media node into post data."""
        if not node:
            return None

        caption_text = ""
        edges = node.get("edge_media_to_caption", {}).get("edges", [])
        if edges:
            caption_text = edges[0].get("node", {}).get("text", "")

        if not caption_text:
            return None

        return {
            "url": f"https://www.instagram.com/p/{node.get('shortcode', '')}/",
            "media_id": node.get("shortcode", node.get("id", "")),
            "media_type": "video" if node.get("is_video") else "photo",
            "caption": caption_text,
            "likes": node.get("edge_liked_by", {}).get("count", 0)
                     or node.get("edge_media_preview_like", {}).get("count", 0),
            "comments_count": node.get("edge_media_to_comment", {}).get("count", 0),
            "user": node.get("owner", {}).get("username", ""),
            "hashtags": re.findall(r"#(\w+)", caption_text),
            "timestamp": datetime.now().isoformat(),
            "image_urls": [node.get("display_url", "")],
            "carousel_count": node.get("edge_sidecar_to_children", {}).get("edges", [{}]).__len__() or 1,
            "views": node.get("video_view_count", 0),
            "comments": [],
            "audio": "",
            "image_descriptions": [],
            "video_url": "",
            "post_time_text": "",
        }

    def _parse_v1_media(self, media: dict) -> dict | None:
        """Parse a v1 API media object into post data."""
        if not media or not isinstance(media, dict):
            return None

        # Caption extraction
        caption_obj = media.get("caption")
        caption_text = ""
        if isinstance(caption_obj, dict):
            caption_text = caption_obj.get("text", "")
        elif isinstance(caption_obj, str):
            caption_text = caption_obj

        if not caption_text:
            return None

        # Username
        user = media.get("user", {})
        username = ""
        if isinstance(user, dict):
            username = user.get("username", "")

        # Media type
        media_type = "photo"
        if media.get("media_type") == 2 or media.get("video_versions"):
            media_type = "video"
        elif media.get("carousel_media"):
            media_type = "carousel"

        # Code/shortcode
        code = media.get("code", media.get("shortcode", media.get("pk", "")))

        # Likes
        likes = media.get("like_count", 0)

        # Image URL
        image_url = ""
        candidates = media.get("image_versions2", {}).get("candidates", [])
        if candidates:
            image_url = candidates[0].get("url", "")

        return {
            "url": f"https://www.instagram.com/p/{code}/" if code else "",
            "media_id": str(code),
            "media_type": media_type,
            "caption": caption_text,
            "likes": likes,
            "comments_count": media.get("comment_count", 0),
            "user": username,
            "hashtags": re.findall(r"#(\w+)", caption_text),
            "timestamp": datetime.now().isoformat(),
            "image_urls": [image_url] if image_url else [],
            "carousel_count": len(media.get("carousel_media", [])) or 1,
            "views": media.get("play_count", media.get("view_count", 0)),
            "comments": [],
            "audio": "",
            "image_descriptions": [],
            "video_url": "",
            "post_time_text": "",
        }

    def crawl_hashtag(self, hashtag: str, max_posts: int = 30) -> list[dict]:
        """Crawl posts from a hashtag page by clicking grid items."""
        tag = hashtag.lstrip("#")
        logger.info("=== Crawling #{} (max {} posts) ===", tag, max_posts)

        if not self.go_to_hashtag(tag):
            return []

        results = []
        skipped_no_caption = 0
        consecutive_fails = 0
        visited_urls = set()

        error_phrases = [
            "링크가 잘못되었거나", "페이지가 삭제", "Page Not Found",
            "문제가 발생하여", "읽어들이지 못했습니다",
            "댓글", "모두 보기", "좋아요", "게시물", "팔로워",
            "로그인", "가입하기", "Something went wrong",
        ]

        # Scroll to load enough grid items
        self._scroll_down(times=max(1, max_posts // 6))
        self._delay(1, 2)

        # Collect grid links for reference
        grid_links = self._page.locator('a[href*="/p/"], a[href*="/reel/"]')
        total_items = grid_links.count()
        logger.info("  Found {} grid items for #{}", total_items, tag)

        for i in range(min(total_items, max_posts)):
            try:
                # Re-locate grid links (DOM may change after navigation)
                grid_links = self._page.locator('a[href*="/p/"], a[href*="/reel/"]')
                if i >= grid_links.count():
                    break

                href = grid_links.nth(i).get_attribute("href", timeout=2000) or ""
                clean_url = href.split("?")[0]
                if clean_url in visited_urls:
                    continue
                visited_urls.add(clean_url)

                # Click the grid item to navigate to the post
                grid_links.nth(i).click(timeout=5000)
                self._delay(3, 5)

                post_data = self._extract_post_data()
                post_data["source"] = f"#{tag}"

                caption = post_data.get("caption", "")
                is_error = not caption or any(ep in caption for ep in error_phrases)

                if is_error:
                    # Try embed fallback
                    full_url = f"https://www.instagram.com{clean_url}" if not clean_url.startswith("http") else clean_url
                    embed_data = self._extract_post_via_embed(full_url)
                    if embed_data:
                        embed_data["source"] = f"#{tag}"
                        post_data = embed_data
                        caption = post_data.get("caption", "")
                        is_error = not caption or any(ep in caption for ep in error_phrases)

                if is_error:
                    skipped_no_caption += 1
                    consecutive_fails += 1
                    if consecutive_fails >= 3:
                        logger.warning("  #{}: {} consecutive fails — rate limited, skipping",
                                       tag, consecutive_fails)
                        break
                elif not self._is_relevant(post_data):
                    consecutive_fails = 0
                else:
                    consecutive_fails = 0
                    results.append(post_data)
                    logger.debug("  [{}/{}] @{}: {}",
                                 i + 1, min(total_items, max_posts),
                                 post_data.get("user", "?"),
                                 caption[:50])

                # Go back to hashtag grid
                self._page.go_back(wait_until="domcontentloaded")
                self._delay(1, 2)
                self._dismiss_overlays()

            except Exception as exc:
                logger.warning("  [{}/{}] Failed: {}", i + 1, min(total_items, max_posts), str(exc)[:80])
                try:
                    self.go_to_hashtag(tag)
                    self._scroll_down(times=max(1, i // 6))
                except Exception:
                    break

            if (i + 1) % 5 == 0:
                logger.info("  #{} progress: {}/{}, {} collected", tag, i + 1, min(total_items, max_posts), len(results))

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"hashtag_{tag}_{self._timestamp()}.json")
        logger.info("Collected {} posts from #{} (no_caption={})",
                     len(results), tag, skipped_no_caption)
        return results

    def crawl_explore(self, max_posts: int = 20) -> list[dict]:
        """Crawl posts from the Explore page."""
        logger.info("=== Crawling Explore page ===")

        if not self.go_to_explore():
            return []

        links = self._collect_grid_links(max_posts)
        results = []

        for link in links:
            try:
                self._page.goto(link, wait_until="domcontentloaded")
                self._delay(2, 4)
                post_data = self._extract_post_data(link)
                post_data["source"] = "explore"
                if post_data["caption"] and self._is_relevant(post_data, strict=True):
                    results.append(post_data)
            except Exception as exc:
                logger.warning("Failed to extract post: {}", exc)

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"explore_{self._timestamp()}.json")
        logger.info("Collected {} posts from explore", len(results))
        return results

    def crawl_reels_feed(self, max_reels: int = 15) -> list[dict]:
        """Crawl reels from the Reels feed (trending reels)."""
        logger.info("=== Crawling Reels feed (max {}) ===", max_reels)

        if not self.go_to_reels():
            return []

        results = []

        for i in range(max_reels):
            try:
                self._delay(3, 5)
                post_data = self._extract_post_data()
                post_data["media_type"] = "reel"
                post_data["source"] = "reels_feed"

                if (post_data["caption"] or post_data["user"]) and self._is_relevant(post_data, strict=True):
                    results.append(post_data)
                    logger.info("  Reel {}: @{} - {}", i + 1, post_data["user"], post_data["caption"][:50])

                # Scroll down to next reel
                self._page.keyboard.press("ArrowDown")
                self._delay(1, 2)

            except Exception as exc:
                logger.warning("Failed to extract reel {}: {}", i, exc)

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"reels_feed_{self._timestamp()}.json")
        logger.info("Collected {} reels from feed", len(results))
        return results

    def search_and_crawl(self, keyword: str, max_results: int = 20) -> list[dict]:
        """Search Instagram and crawl results by clicking grid items."""
        logger.info("=== Searching '{}' ===", keyword)

        self._page.goto(
            f"https://www.instagram.com/explore/search/keyword/?q={keyword}",
            wait_until="domcontentloaded",
        )
        self._delay(3, 5)

        # Scroll to load grid items
        self._scroll_down(times=max(1, max_results // 6))
        self._delay(1, 2)

        results = []
        skipped_no_caption = 0
        consecutive_fails = 0
        visited_urls = set()
        error_phrases = [
            "링크가 잘못되었거나", "페이지가 삭제", "Page Not Found",
            "문제가 발생하여", "읽어들이지 못했습니다",
            "댓글", "모두 보기", "좋아요", "게시물", "팔로워",
            "로그인", "가입하기", "Something went wrong",
        ]

        grid_links = self._page.locator('a[href*="/p/"], a[href*="/reel/"]')
        total_items = grid_links.count()

        for i in range(min(total_items, max_results)):
            try:
                grid_links = self._page.locator('a[href*="/p/"], a[href*="/reel/"]')
                if i >= grid_links.count():
                    break

                href = grid_links.nth(i).get_attribute("href", timeout=2000) or ""
                clean_url = href.split("?")[0]
                if clean_url in visited_urls:
                    continue
                visited_urls.add(clean_url)

                grid_links.nth(i).click(timeout=5000)
                self._delay(3, 5)

                post_data = self._extract_post_data()
                post_data["source"] = f"search:{keyword}"

                caption = post_data.get("caption", "")
                is_error = not caption or any(ep in caption for ep in error_phrases)
                if is_error:
                    skipped_no_caption += 1
                    consecutive_fails += 1
                    if consecutive_fails >= 3:
                        logger.warning("  '{}': rate limited, skipping", keyword)
                        break
                elif self._is_relevant(post_data):
                    consecutive_fails = 0
                    results.append(post_data)
                else:
                    consecutive_fails = 0

                self._page.go_back(wait_until="domcontentloaded")
                self._delay(1, 2)
                self._dismiss_overlays()

            except Exception as exc:
                logger.warning("  [{}/{}] Failed: {}", i + 1, min(total_items, max_results), str(exc)[:80])
                try:
                    self._page.goto(
                        f"https://www.instagram.com/explore/search/keyword/?q={keyword}",
                        wait_until="domcontentloaded",
                    )
                    self._delay(2, 3)
                    self._scroll_down(times=max(1, i // 6))
                except Exception:
                    break

            if (i + 1) % 5 == 0:
                logger.info("  '{}' progress: {}/{}, {} collected",
                            keyword, i + 1, min(total_items, max_results), len(results))

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"search_{keyword}_{self._timestamp()}.json")
        logger.info("Collected {} results for '{}' (no_caption={})",
                     len(results), keyword, skipped_no_caption)
        return results

    # ------------------------------------------------------------------
    # Bulk crawl
    # ------------------------------------------------------------------

    def bulk_crawl(
        self,
        usernames: list[str] = None,
        hashtags: list[str] = None,
        search_keywords: list[str] = None,
        posts_per_source: int = 20,
        posts_per_user: int | None = None,
        crawl_explore: bool = True,
        crawl_reels_feed: bool = True,
    ) -> dict[str, Any]:
        """Run comprehensive crawl across all sources.

        Parameters
        ----------
        posts_per_user : int | None
            유저당 수집 게시글 수. None이면 posts_per_source와 동일.
            다양한 유저에서 조금씩 수집하려면 작은 값(3-5)으로 설정.
        """
        logger.info("=" * 60)
        logger.info("BULK CRAWL STARTING")
        logger.info("=" * 60)

        user_count = posts_per_user if posts_per_user is not None else posts_per_source

        self._all_collected = []
        stats = {"users": 0, "hashtags": 0, "searches": 0, "total": 0}

        if usernames:
            for u in usernames:
                try:
                    self.crawl_user(u, max_posts=user_count)
                    stats["users"] += 1
                except Exception as exc:
                    logger.error("Failed @{}: {}", u, exc)

        if hashtags:
            for h in hashtags:
                try:
                    # Try intercept method first (no rate limit), fallback to click
                    results = self.crawl_hashtag_intercept(h, max_posts=posts_per_source)
                    if not results:
                        results = self.crawl_hashtag(h, max_posts=posts_per_source)
                    stats["hashtags"] += 1
                except Exception as exc:
                    logger.error("Failed #{}: {}", h, exc)

        if search_keywords:
            for kw in search_keywords:
                try:
                    self.search_and_crawl(kw, max_results=posts_per_source)
                    stats["searches"] += 1
                except Exception as exc:
                    logger.error("Failed search '{}': {}", kw, exc)

        if crawl_explore:
            try:
                self.crawl_explore(max_posts=posts_per_source)
            except Exception as exc:
                logger.error("Explore failed: {}", exc)

        if crawl_reels_feed:
            try:
                self.crawl_reels_feed(max_reels=15)
            except Exception as exc:
                logger.error("Reels feed failed: {}", exc)

        stats["total"] = len(self._all_collected)

        # Save combined
        if self._all_collected:
            self._save_json(self._all_collected, f"bulk_{self._timestamp()}.json")

        logger.info("=" * 60)
        logger.info("BULK CRAWL COMPLETE: {} items", stats["total"])
        logger.info("=" * 60)
        return stats

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_count(text: str) -> int:
        """Parse '1.2K', '3.5M', '1,234' into int."""
        text = text.strip().replace(",", "")
        multiplier = 1
        if text.endswith(("K", "k")):
            multiplier = 1000
            text = text[:-1]
        elif text.endswith(("M", "m")):
            multiplier = 1_000_000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return 0

    def get_all_collected(self) -> list[dict]:
        return self._all_collected

    def close(self) -> None:
        """Close browser and cleanup."""
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass
        logger.info("Browser closed")

    def __del__(self):
        self.close()
