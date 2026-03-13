#!/usr/bin/env python3
"""Debug post detail page structure for data extraction."""
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

    # Go to a known post from @instagram
    test_url = "https://www.instagram.com/instagram/reel/DVy5TZMkdgn/"
    print(f"\nNavigating to: {test_url}")
    page.goto(test_url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    crawler.screenshot("post_detail")

    # Analyze page structure
    print("\n=== Page URL ===")
    print(page.url)

    print("\n=== All text in span[dir='auto'] ===")
    spans = page.locator('span[dir="auto"]')
    print(f"  count: {spans.count()}")
    for i in range(min(spans.count(), 20)):
        try:
            text = spans.nth(i).text_content(timeout=1000)
            if text:
                print(f"  [{i}] ({len(text)} chars): {text[:120]}")
        except:
            pass

    print("\n=== All h1 elements ===")
    h1s = page.locator("h1")
    for i in range(h1s.count()):
        try:
            text = h1s.nth(i).text_content(timeout=1000)
            print(f"  [{i}]: {text[:200]}")
        except:
            pass

    print("\n=== span elements with long text ===")
    all_spans = page.locator("span")
    long_texts = []
    for i in range(min(all_spans.count(), 100)):
        try:
            text = all_spans.nth(i).text_content(timeout=500)
            if text and len(text.strip()) > 20:
                long_texts.append((i, text.strip()))
        except:
            pass
    for idx, t in long_texts[:15]:
        print(f"  [span {idx}] ({len(t)} chars): {t[:150]}")

    print("\n=== Likes/Views area ===")
    # Check sections
    sections = page.locator("section")
    print(f"  <section> count: {sections.count()}")
    for i in range(sections.count()):
        try:
            text = sections.nth(i).text_content(timeout=1000)
            if text:
                print(f"  [section {i}]: {text[:200]}")
        except:
            pass

    print("\n=== Links with usernames ===")
    user_links = page.locator('a[href^="/"][role="link"]')
    print(f"  a[role=link]: {user_links.count()}")
    for i in range(min(user_links.count(), 10)):
        try:
            href = user_links.nth(i).get_attribute("href", timeout=500)
            text = user_links.nth(i).text_content(timeout=500)
            print(f"  [{i}] href={href}, text={text[:50] if text else ''}")
        except:
            pass

    # Also check header area
    print("\n=== Header area ===")
    headers = page.locator("header")
    for i in range(headers.count()):
        try:
            text = headers.nth(i).text_content(timeout=1000)
            print(f"  [header {i}]: {text[:200]}")
        except:
            pass

    # Now scroll down to see comments
    print("\n=== Scrolling for comments ===")
    page.evaluate("window.scrollBy(0, 500)")
    page.wait_for_timeout(2000)
    crawler.screenshot("post_detail_scrolled")

    # Check for comment elements
    print("\n=== ul elements ===")
    uls = page.locator("ul")
    print(f"  <ul> count: {uls.count()}")

    # Try to find "좋아요" text
    print("\n=== Text containing '좋아요' or 'like' ===")
    likes_el = page.locator(':text("좋아요"), :text("likes"), :text("like")')
    print(f"  count: {likes_el.count()}")
    for i in range(min(likes_el.count(), 5)):
        try:
            text = likes_el.nth(i).text_content(timeout=500)
            print(f"  [{i}]: {text[:100]}")
        except:
            pass

    # Aria labels (useful for finding interactive elements)
    print("\n=== Elements with aria-label ===")
    aria_els = page.locator("[aria-label]")
    for i in range(min(aria_els.count(), 30)):
        try:
            label = aria_els.nth(i).get_attribute("aria-label", timeout=500)
            tag = aria_els.nth(i).evaluate("el => el.tagName", timeout=500)
            print(f"  [{i}] <{tag}> aria-label=\"{label}\"")
        except:
            pass

finally:
    crawler.close()
