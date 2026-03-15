#!/usr/bin/env python3
"""크롤러 캡션 추출 테스트 — 해시태그 1개에서 게시글 3개만 수집."""
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
        print("로그인 실패!")
        sys.exit(1)

    print("\n=== 테스트: #카페스타그램 에서 3개 수집 ===\n")
    results = crawler.crawl_hashtag("카페스타그램", max_posts=3)

    print(f"\n수집 결과: {len(results)}개")
    for i, r in enumerate(results):
        print(f"\n--- [{i+1}] @{r.get('user', '?')} ---")
        print(f"  캡션: {r.get('caption', '(없음)')[:100]}")
        print(f"  좋아요: {r.get('likes', 0)}")
        print(f"  URL: {r.get('url', '')}")

    if not results:
        print("\n캡션 추출 실패 — 스크린샷 저장 중...")
        # 게시글 하나 직접 방문해서 디버그
        crawler.go_to_hashtag("카페스타그램")
        import time; time.sleep(3)
        links = crawler._collect_grid_links(1)
        if links:
            crawler._page.goto(links[0], wait_until="domcontentloaded")
            time.sleep(5)
            crawler.screenshot("debug_post")
            # 페이지 HTML 일부 저장
            html = crawler._page.content()
            debug_path = PROJECT_ROOT / "data" / "raw" / "debug_page.html"
            debug_path.write_text(html[:50000], "utf-8")
            print(f"  디버그 HTML 저장: {debug_path}")
            print(f"  URL: {links[0]}")
finally:
    crawler.close()
