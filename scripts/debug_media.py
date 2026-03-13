#!/usr/bin/env python3
"""Debug: inspect media elements on Instagram post pages."""
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

    page = crawler._page

    # Test with a photo post and a reel
    test_urls = [
        "https://www.instagram.com/explore/",  # go to explore first to find posts
    ]

    # Go to explore, get first few links
    page.goto("https://www.instagram.com/explore/", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    crawler._dismiss_overlays()

    anchors = page.locator('a[href*="/p/"], a[href*="/reel/"]')
    links = []
    for i in range(min(anchors.count(), 5)):
        try:
            href = anchors.nth(i).get_attribute("href", timeout=500)
            if href:
                if not href.startswith("http"):
                    href = f"https://www.instagram.com{href}"
                links.append(href)
        except:
            pass

    print(f"Found {len(links)} links")

    for link in links[:2]:
        print(f"\n{'='*60}")
        print(f"Visiting: {link}")
        page.goto(link, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        crawler._dismiss_overlays()

        # Check for images
        print("\n--- Images ---")
        imgs = page.locator("img")
        for i in range(min(imgs.count(), 15)):
            try:
                src = imgs.nth(i).get_attribute("src", timeout=500) or ""
                alt = imgs.nth(i).get_attribute("alt", timeout=500) or ""
                width = imgs.nth(i).get_attribute("width", timeout=500) or ""
                cls = imgs.nth(i).get_attribute("class", timeout=500) or ""
                if src and "scontent" in src:  # Instagram CDN images
                    print(f"  [{i}] {width}px alt='{alt[:80]}' src={src[:100]}...")
            except:
                pass

        # Check for videos
        print("\n--- Videos ---")
        videos = page.locator("video")
        print(f"  <video> count: {videos.count()}")
        for i in range(videos.count()):
            try:
                src = videos.nth(i).get_attribute("src", timeout=500) or ""
                poster = videos.nth(i).get_attribute("poster", timeout=500) or ""
                print(f"  [{i}] src={src[:100]}...")
                if poster:
                    print(f"       poster={poster[:100]}...")

                # Check source elements inside video
                sources = videos.nth(i).locator("source")
                for j in range(sources.count()):
                    s_src = sources.nth(j).get_attribute("src", timeout=500) or ""
                    s_type = sources.nth(j).get_attribute("type", timeout=500) or ""
                    print(f"       source[{j}] type={s_type} src={s_src[:100]}...")
            except:
                pass

        # Check for carousel indicators (multiple images)
        print("\n--- Carousel ---")
        carousel_btns = page.locator('button[aria-label*="다음"], button[aria-label*="Next"]')
        print(f"  Next button: {carousel_btns.count()}")
        dots = page.locator('div[class*="indicator"], div[role="tablist"]')
        print(f"  Indicator dots: {dots.count()}")

        # Check aria-labels for media info
        print("\n--- Media aria-labels ---")
        media_els = page.locator('[aria-label*="사진"], [aria-label*="Photo"], [aria-label*="동영상"], [aria-label*="Video"]')
        for i in range(min(media_els.count(), 5)):
            try:
                label = media_els.nth(i).get_attribute("aria-label", timeout=500)
                tag = media_els.nth(i).evaluate("el => el.tagName", timeout=500)
                print(f"  [{i}] <{tag}> aria-label='{label}'")
            except:
                pass

finally:
    crawler.close()
