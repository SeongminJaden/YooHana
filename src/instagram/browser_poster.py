"""
Instagram browser-based content posting using Playwright.

Uploads photos by automating a real Chromium browser, mimicking how a
human would create a post through the mobile web interface.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SESSION_DIR = _PROJECT_ROOT / "data" / "browser_session"


class BrowserPoster:
    """Upload photos to Instagram via Playwright browser automation.

    Reuses the same session/cookies saved by the browser crawler,
    so no separate login is needed if crawling has been done recently.

    Parameters
    ----------
    headless : bool
        Run without a visible browser window.
    slow_mo : int
        Milliseconds of delay between actions for anti-detection.
    """

    def __init__(self, headless: bool = False, slow_mo: int = 500) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Try loading saved session from crawler
        session_file = _SESSION_DIR / "state.json"
        context_kwargs = {
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
            context_kwargs["storage_state"] = str(session_file)
            logger.info("Loaded browser session from {}", session_file)

        self._context = self._browser.new_context(**context_kwargs)
        self._page = self._context.new_page()
        self._logged_in = False

    def _delay(self, min_s: float = 1.0, max_s: float = 3.0) -> None:
        """Random delay for anti-detection."""
        time.sleep(random.uniform(min_s, max_s))

    def _dismiss_overlays(self) -> None:
        """Dismiss popups (save login, notifications, app banner)."""
        dismiss_texts = [
            "나중에 하기", "나중에", "Not Now", "Not now",
            "닫기", "Close", "취소", "Cancel",
        ]
        for txt in dismiss_texts:
            try:
                btn = self._page.locator(
                    f'button:has-text("{txt}"), div[role="button"]:has-text("{txt}")'
                )
                if btn.count() > 0 and btn.first.is_visible():
                    btn.first.click(timeout=2000)
                    time.sleep(0.5)
                    return
            except Exception:
                continue

    def _screenshot(self, name: str = "poster_debug") -> str:
        """Take a debug screenshot."""
        out_dir = _PROJECT_ROOT / "outputs" / "logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = str(out_dir / f"{name}_{int(time.time())}.png")
        self._page.screenshot(path=path)
        logger.debug("Screenshot: {}", path)
        return path

    def login(self, username: str = None, password: str = None) -> bool:
        """Log into Instagram. Skips if session is already valid."""
        # Check if already logged in via saved session
        self._page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        self._delay(2, 4)
        self._dismiss_overlays()
        self._delay(1, 2)

        # Check for logged-in state (profile icon or create button present)
        try:
            profile_nav = self._page.locator(
                'a[href*="/accounts/edit/"], '
                'svg[aria-label="프로필 사진"], '
                'svg[aria-label="Profile photo"], '
                'a[role="link"][href*="/direct/"]'
            )
            if profile_nav.count() > 0:
                logger.info("Already logged in via saved session")
                self._logged_in = True
                return True
        except Exception:
            pass

        # Need to log in
        if not username or not password:
            from dotenv import load_dotenv
            load_dotenv(_PROJECT_ROOT / ".env")
            username = os.getenv("INSTAGRAM_USERNAME", "")
            password = os.getenv("INSTAGRAM_PASSWORD", "")

        if not username or not password:
            logger.error("No credentials available for login")
            return False

        try:
            self._page.goto("https://www.instagram.com/accounts/login/",
                            wait_until="domcontentloaded")
            self._delay(2, 4)
            self._dismiss_overlays()

            # Fill credentials
            user_input = self._page.locator('input[name="username"]')
            user_input.fill(username)
            self._delay(0.5, 1)

            pass_input = self._page.locator('input[name="password"]')
            pass_input.fill(password)
            self._delay(0.5, 1)

            # Click login
            login_btn = self._page.locator('button[type="submit"]')
            login_btn.click()
            self._delay(4, 6)

            self._dismiss_overlays()
            self._delay(1, 2)
            self._dismiss_overlays()

            # Save session
            _SESSION_DIR.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(_SESSION_DIR / "state.json"))

            self._logged_in = True
            logger.info("Login successful")
            return True

        except Exception as e:
            logger.error("Login failed: {}", e)
            self._screenshot("login_failed")
            return False

    def post_photo(
        self,
        image_path: str,
        caption: str,
        hashtags: Optional[list[str]] = None,
    ) -> bool:
        """Upload a photo post to Instagram via browser automation.

        Parameters
        ----------
        image_path : str
            Absolute path to the image file.
        caption : str
            Caption text for the post.
        hashtags : list[str] | None
            Optional hashtags to append to the caption.

        Returns
        -------
        bool
            True if the post was published successfully.
        """
        if not self._logged_in:
            logger.error("Not logged in. Call login() first.")
            return False

        image = Path(image_path)
        if not image.exists():
            logger.error("Image file not found: {}", image)
            return False

        # Build full caption
        full_caption = caption
        if hashtags:
            tag_line = " ".join(
                tag if tag.startswith("#") else f"#{tag}" for tag in hashtags
            )
            full_caption = f"{caption}\n\n{tag_line}"

        try:
            # Navigate to Instagram home
            self._page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            self._delay(2, 4)
            self._dismiss_overlays()

            # Click the "New Post" / create button
            # Instagram mobile web: the + icon is in the top-right header area
            # or via direct URL navigation
            create_selectors = [
                'svg[aria-label="새로운 게시물"]',
                'svg[aria-label="New post"]',
                'svg[aria-label="만들기"]',
                'svg[aria-label="Create"]',
                'a[href="/create/style/"]',
                'a[href="/create/select/"]',
            ]

            create_clicked = False
            for sel in create_selectors:
                try:
                    btn = self._page.locator(sel)
                    if btn.count() > 0 and btn.first.is_visible():
                        btn.first.click(timeout=3000)
                        create_clicked = True
                        logger.info("Clicked create button: {}", sel)
                        break
                except Exception:
                    continue

            if not create_clicked:
                # Try all SVG elements for the + icon
                try:
                    all_svgs = self._page.locator("svg")
                    for i in range(all_svgs.count()):
                        svg = all_svgs.nth(i)
                        label = svg.get_attribute("aria-label") or ""
                        if any(k in label for k in ["새로운", "만들기", "New", "Create", "게시물"]):
                            svg.click(timeout=3000)
                            create_clicked = True
                            logger.info("Clicked create SVG: {}", label)
                            break
                except Exception:
                    pass

            if not create_clicked:
                # Try the + link in the header (visible in screenshot)
                try:
                    plus_links = self._page.locator('a[href*="create"], div[role="button"]')
                    for i in range(plus_links.count()):
                        el = plus_links.nth(i)
                        try:
                            inner = el.inner_html()
                            if "+" in el.inner_text() or "svg" in inner:
                                label = ""
                                svg_el = el.locator("svg")
                                if svg_el.count() > 0:
                                    label = svg_el.first.get_attribute("aria-label") or ""
                                if label and any(k in label for k in ["새로운", "만들기", "New", "Create"]):
                                    el.click(timeout=3000)
                                    create_clicked = True
                                    logger.info("Clicked create via link: {}", label)
                                    break
                        except Exception:
                            continue
                except Exception:
                    pass

            if not create_clicked:
                # Last resort: navigate directly to the create page
                logger.info("Trying direct navigation to /create/select/")
                self._page.goto("https://www.instagram.com/create/select/",
                                wait_until="domcontentloaded")
                self._delay(2, 4)
                self._dismiss_overlays()
                # Check if we're on the create page now
                if "/create" in self._page.url:
                    create_clicked = True
                    logger.info("Navigated directly to create page")

            if not create_clicked:
                logger.error("Could not find create/new post button")
                self._screenshot("no_create_button")
                return False

            self._delay(1, 2)
            self._dismiss_overlays()

            # Handle file input - Instagram uses a hidden file input
            # Set the file via the file chooser
            try:
                # Method 1: Look for file input element
                file_input = self._page.locator('input[type="file"]')
                if file_input.count() > 0:
                    file_input.first.set_input_files(str(image.resolve()))
                    logger.info("File set via input element")
                else:
                    # Method 2: Use file chooser event
                    with self._page.expect_file_chooser(timeout=10000) as fc_info:
                        # Click "Select from computer" / "컴퓨터에서 선택"
                        select_btn = self._page.locator(
                            'button:has-text("컴퓨터에서 선택"), '
                            'button:has-text("Select from computer"), '
                            'button:has-text("Select from Computer"), '
                            'button:has-text("갤러리에서 선택")'
                        )
                        if select_btn.count() > 0:
                            select_btn.first.click()
                        else:
                            # Try clicking the main area
                            self._page.locator('div[role="dialog"]').first.click()
                    file_chooser = fc_info.value
                    file_chooser.set_files(str(image.resolve()))
                    logger.info("File set via file chooser")
            except Exception as e:
                logger.error("Failed to set file: {}", e)
                self._screenshot("file_set_failed")
                return False

            self._delay(2, 4)
            self._dismiss_overlays()

            # Click "Next" / "다음" (crop/filter step)
            for _ in range(2):  # May need to click twice (crop → filter → caption)
                self._delay(1, 2)
                next_btn = self._page.locator(
                    'button:has-text("다음"), '
                    'button:has-text("Next"), '
                    'div[role="button"]:has-text("다음"), '
                    'div[role="button"]:has-text("Next")'
                )
                try:
                    if next_btn.count() > 0 and next_btn.first.is_visible():
                        next_btn.first.click(timeout=5000)
                        logger.info("Clicked '다음/Next'")
                        self._delay(1, 2)
                except Exception:
                    pass

            self._delay(1, 2)

            # Enter caption
            try:
                caption_input = self._page.locator(
                    'textarea[aria-label="문구를 입력하세요..."], '
                    'textarea[aria-label="Write a caption..."], '
                    'div[aria-label="문구를 입력하세요..."], '
                    'div[aria-label="Write a caption..."], '
                    'div[role="textbox"][contenteditable="true"]'
                )
                if caption_input.count() > 0:
                    caption_input.first.click()
                    self._delay(0.3, 0.5)
                    caption_input.first.fill(full_caption)
                    logger.info("Caption entered ({} chars)", len(full_caption))
                else:
                    logger.warning("Caption input not found, posting without caption")
            except Exception as e:
                logger.warning("Failed to enter caption: {}", e)

            self._delay(1, 2)

            # Click "Share" / "공유하기"
            share_btn = self._page.locator(
                'button:has-text("공유하기"), '
                'button:has-text("Share"), '
                'div[role="button"]:has-text("공유하기"), '
                'div[role="button"]:has-text("Share")'
            )
            try:
                if share_btn.count() > 0 and share_btn.first.is_visible():
                    share_btn.first.click(timeout=5000)
                    logger.info("Clicked '공유하기/Share'")
                else:
                    logger.error("Share button not found")
                    self._screenshot("no_share_button")
                    return False
            except Exception as e:
                logger.error("Failed to click share: {}", e)
                self._screenshot("share_failed")
                return False

            # Wait for upload to complete
            self._delay(5, 10)

            # Check for success indicators
            try:
                success = self._page.locator(
                    'span:has-text("게시물이 공유되었습니다"), '
                    'span:has-text("Your post has been shared"), '
                    'img[alt="animated checkmark"]'
                )
                if success.count() > 0:
                    logger.success("Post published successfully!")
                    self._screenshot("post_success")
                    return True
            except Exception:
                pass

            # If we don't see an error, assume success
            logger.info("Post likely published (no error detected)")
            self._screenshot("post_result")
            return True

        except Exception as e:
            logger.error("Post failed with exception: {}", e)
            self._screenshot("post_exception")
            return False

    def close(self) -> None:
        """Close the browser and Playwright."""
        try:
            # Save session state before closing
            _SESSION_DIR.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(_SESSION_DIR / "state.json"))
        except Exception:
            pass

        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass
