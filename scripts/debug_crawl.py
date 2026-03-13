#!/usr/bin/env python3
"""Debug script to inspect Instagram page structure."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.browser_crawler import InstagramBrowserCrawler, _RAW_DATA_DIR

crawler = InstagramBrowserCrawler(headless=False, slow_mo=300)

try:
    # Login
    if not crawler.login():
        print("Login failed!")
        sys.exit(1)
    print("Logged in!")

    page = crawler._page

    # Navigate to user profile
    username = sys.argv[1] if len(sys.argv) > 1 else "hi_sseul"
    print(f"\nNavigating to @{username}...")
    page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    crawler.screenshot(f"profile_{username}")

    # Check for all anchor tags
    all_anchors = page.locator("a")
    print(f"\nTotal <a> tags: {all_anchors.count()}")

    # List all href values
    hrefs = []
    for i in range(min(all_anchors.count(), 100)):
        try:
            href = all_anchors.nth(i).get_attribute("href", timeout=1000)
            if href:
                hrefs.append(href)
        except:
            pass

    print("\nAll hrefs on profile page:")
    for h in hrefs:
        print(f"  {h}")

    # Look specifically for post/reel links
    post_links = [h for h in hrefs if "/p/" in h or "/reel/" in h]
    print(f"\nPost/Reel links found: {len(post_links)}")
    for pl in post_links:
        print(f"  {pl}")

    # Check grid structure
    print("\n--- Grid analysis ---")
    article = page.locator("article")
    print(f"<article> elements: {article.count()}")

    main_el = page.locator("main")
    print(f"<main> elements: {main_el.count()}")

    # Check various grid selectors
    selectors_to_try = [
        'a[href*="/p/"]',
        'a[href*="/reel/"]',
        'div[class*="Grid"]',
        'div[class*="grid"]',
        'div[style*="grid"]',
        'article a',
        'main a',
        'div[role="tablist"]',
        'div[role="tab"]',
    ]

    for sel in selectors_to_try:
        count = page.locator(sel).count()
        if count > 0:
            print(f"  '{sel}': {count} matches")

    # Try scrolling and see if more links appear
    print("\nScrolling down...")
    page.evaluate("window.scrollBy(0, window.innerHeight)")
    page.wait_for_timeout(3000)
    crawler.screenshot(f"profile_{username}_scrolled")

    # Re-check for post links after scroll
    all_anchors2 = page.locator("a")
    hrefs2 = []
    for i in range(min(all_anchors2.count(), 100)):
        try:
            href = all_anchors2.nth(i).get_attribute("href", timeout=1000)
            if href:
                hrefs2.append(href)
        except:
            pass

    post_links2 = [h for h in hrefs2 if "/p/" in h or "/reel/" in h]
    print(f"\nPost/Reel links after scroll: {len(post_links2)}")
    for pl in post_links2[:10]:
        print(f"  {pl}")

finally:
    crawler.close()
