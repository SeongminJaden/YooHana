#!/usr/bin/env python3
"""Test script for Playwright-based Instagram browser crawler."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.browser_crawler import InstagramBrowserCrawler

logger = get_logger()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test Browser Crawler")
    parser.add_argument("--headless", action="store_true", help="Run headless (no GUI)")
    parser.add_argument("--mode", choices=["login", "user", "hashtag", "explore", "reels", "full"],
                       default="login", help="Test mode")
    parser.add_argument("--target", type=str, default="hi_sseul", help="Username or hashtag to crawl")
    parser.add_argument("--count", type=int, default=5, help="Max posts to collect")
    args = parser.parse_args()

    headless = args.headless
    logger.info("Starting browser crawler (headless={})", headless)

    crawler = InstagramBrowserCrawler(headless=headless, slow_mo=500)

    try:
        # Step 1: Login
        logger.info("--- Step 1: Login ---")
        success = crawler.login()
        if not success:
            logger.error("Login failed! Check screenshot in data/raw/")
            crawler.screenshot("login_failed_final")
            return

        logger.info("Login OK!")
        crawler.screenshot("logged_in")

        if args.mode == "login":
            logger.info("Login-only test complete.")
            return

        # Step 2: Crawl based on mode
        if args.mode == "user":
            logger.info("--- Step 2: Crawl user @{} ---", args.target)
            results = crawler.crawl_user(args.target, max_posts=args.count)
            logger.info("Got {} posts from @{}", len(results), args.target)
            for r in results[:3]:
                logger.info("  - {}: {}", r.get("media_type"), r.get("caption", "")[:80])

        elif args.mode == "hashtag":
            tag = args.target.lstrip("#")
            logger.info("--- Step 2: Crawl #{} ---", tag)
            results = crawler.crawl_hashtag(tag, max_posts=args.count)
            logger.info("Got {} posts from #{}", len(results), tag)

        elif args.mode == "explore":
            logger.info("--- Step 2: Crawl Explore ---")
            results = crawler.crawl_explore(max_posts=args.count)
            logger.info("Got {} posts from explore", len(results))

        elif args.mode == "reels":
            logger.info("--- Step 2: Crawl Reels feed ---")
            results = crawler.crawl_reels_feed(max_reels=args.count)
            logger.info("Got {} reels", len(results))

        elif args.mode == "full":
            logger.info("--- Step 2: Full test crawl ---")
            stats = crawler.bulk_crawl(
                usernames=[args.target],
                hashtags=["일상스타그램"],
                posts_per_source=args.count,
                crawl_explore=True,
                crawl_reels_feed=True,
            )
            logger.info("Full crawl stats: {}", stats)

        # Summary
        all_data = crawler.get_all_collected()
        logger.info("=== TOTAL COLLECTED: {} items ===", len(all_data))

    finally:
        crawler.close()


if __name__ == "__main__":
    main()
