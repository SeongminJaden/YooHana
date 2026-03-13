#!/usr/bin/env python3
"""Debug: try explore page and a public user."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.browser_crawler import InstagramBrowserCrawler

crawler = InstagramBrowserCrawler(headless=False, slow_mo=300)

try:
    if not crawler.login():
        print("Login failed!")
        sys.exit(1)
    print("Logged in!")

    page = crawler._page

    # Try explore page first
    print("\n=== Explore Page ===")
    page.goto("https://www.instagram.com/explore/", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    crawler.screenshot("explore")

    # Check links
    all_anchors = page.locator("a")
    hrefs = []
    for i in range(min(all_anchors.count(), 200)):
        try:
            href = all_anchors.nth(i).get_attribute("href", timeout=500)
            if href:
                hrefs.append(href)
        except:
            pass

    post_links = [h for h in hrefs if "/p/" in h or "/reel/" in h]
    print(f"Post/Reel links on explore: {len(post_links)}")
    for pl in post_links[:10]:
        print(f"  {pl}")

    # Try clicking on a grid item if post links not found
    if not post_links:
        print("\nNo /p/ or /reel/ links. Checking for clickable grid items...")
        # Try img inside grid
        imgs = page.locator("img")
        print(f"  <img> count: {imgs.count()}")

        # Try divs with background images (grid thumbnails)
        divs_with_role = page.locator('div[role="button"]')
        print(f"  div[role=button]: {divs_with_role.count()}")

        # Check all link patterns
        all_patterns = set()
        for h in hrefs:
            # Extract pattern: first two path segments
            parts = h.strip("/").split("/")
            if parts:
                all_patterns.add(parts[0])
        print(f"  Link path prefixes: {sorted(all_patterns)}")

    # Try a known public user
    print("\n=== Trying public profile ===")
    # Use Instagram's own account as it's always public
    page.goto("https://www.instagram.com/instagram/", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    crawler.screenshot("profile_instagram")

    all_anchors2 = page.locator("a")
    hrefs2 = []
    for i in range(min(all_anchors2.count(), 200)):
        try:
            href = all_anchors2.nth(i).get_attribute("href", timeout=500)
            if href:
                hrefs2.append(href)
        except:
            pass

    post_links2 = [h for h in hrefs2 if "/p/" in h or "/reel/" in h]
    print(f"Post/Reel links on @instagram: {len(post_links2)}")
    for pl in post_links2[:10]:
        print(f"  {pl}")

    if not post_links2:
        print("\nAll hrefs on @instagram profile:")
        for h in hrefs2:
            print(f"  {h}")

        # Check for grid content via other selectors
        print("\nChecking alternative grid selectors...")
        for sel in ['article a', 'main article', 'div[class*="_aagw"]', 'div[class*="x1lliihq"]',
                    'a[href*="/p/"]', 'a[href*="/reel/"]', 'a[role="link"]']:
            c = page.locator(sel).count()
            if c > 0:
                print(f"  '{sel}': {c}")

        # Scroll to load grid content
        print("\nScrolling down to load grid...")
        for i in range(3):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(2000)

        crawler.screenshot("profile_instagram_scrolled")

        all_anchors3 = page.locator("a")
        hrefs3 = []
        for i in range(min(all_anchors3.count(), 300)):
            try:
                href = all_anchors3.nth(i).get_attribute("href", timeout=500)
                if href:
                    hrefs3.append(href)
            except:
                pass

        post_links3 = [h for h in hrefs3 if "/p/" in h or "/reel/" in h]
        print(f"Post/Reel links after scroll: {len(post_links3)}")
        for pl in post_links3[:10]:
            print(f"  {pl}")

finally:
    crawler.close()
