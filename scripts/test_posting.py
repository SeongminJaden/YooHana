#!/usr/bin/env python3
"""Test Instagram posting via Playwright browser automation."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.instagram.browser_poster import BrowserPoster

logger = get_logger()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Instagram Posting Test")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--image", type=str, default=None, help="Image path to post")
    parser.add_argument("--caption", type=str, default=None, help="Caption text")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only login and check, don't actually post")
    args = parser.parse_args()

    # Default test image
    if args.image is None:
        test_image = PROJECT_ROOT / "outputs" / "images" / "test_post.jpg"
        if not test_image.exists():
            logger.info("Creating test image...")
            from scripts.create_test_image import create_test_image
            create_test_image(str(test_image))
        args.image = str(test_image)

    # Default caption
    if args.caption is None:
        args.caption = (
            "테스트 게시물입니다 ✨\n"
            "AI Influencer 프로젝트 첫 포스팅 테스트!"
        )

    hashtags = ["AIInfluencer", "테스트", "첫게시물", "test"]

    poster = BrowserPoster(headless=args.headless, slow_mo=500)

    try:
        # Login
        logger.info("로그인 시도...")
        if not poster.login():
            logger.error("로그인 실패!")
            sys.exit(1)
        logger.info("로그인 성공!")

        if args.dry_run:
            logger.info("드라이런 모드 - 포스팅은 건너뜁니다")
            return

        # Post
        logger.info("포스팅 시도...")
        logger.info("  이미지: {}", args.image)
        logger.info("  캡션: {}", args.caption[:50])

        success = poster.post_photo(
            image_path=args.image,
            caption=args.caption,
            hashtags=hashtags,
        )

        if success:
            logger.success("포스팅 성공!")
        else:
            logger.error("포스팅 실패. 스크린샷을 확인하세요.")

    finally:
        poster.close()


if __name__ == "__main__":
    main()
