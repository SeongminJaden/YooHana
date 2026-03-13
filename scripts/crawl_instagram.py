#!/usr/bin/env python3
"""Instagram browser crawler - Playwright 기반 크롤링 (페르소나 맞춤 필터링)."""
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


# ==========================================================
# 한국 라이프스타일/패션 인플루언서 (공개 계정)
# ==========================================================
TARGET_USERS = [
    "ch_eeze",           # 감성/일상
    "hwa.min",           # 패션/뷰티
    "soovely_",          # 카페/일상
    "dear.zia",          # 패션/일상
    "minhee_0610",       # OOTD/일상
    "soyou_x",           # 패션
]

# 한국어 해시태그
TARGET_HASHTAGS = [
    "일상스타그램",
    "카페스타그램",
    "데일리룩",
    "서울카페",
    "오오티디",
    "감성스타그램",
    "맛집스타그램",
    "봄코디",
    "패션스타그램",
    "셀스타그램",
    "코디추천",
    "서울맛집",
    "한강",
    "피크닉",
]

# 한국어 검색 키워드
SEARCH_KEYWORDS = [
    "일상 브이로그",
    "서울 카페 추천",
    "봄 데일리룩",
    "한국 패션 코디",
    "감성 사진",
    "서울 핫플레이스",
]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Instagram Browser Crawler (한국어)")
    parser.add_argument("--mode", choices=["full", "users", "hashtags", "search", "explore", "reels", "test"],
                       default="test", help="크롤링 모드")
    parser.add_argument("--count", type=int, default=20, help="소스당 수집할 게시글 수")
    parser.add_argument("--headless", action="store_true", help="헤드리스 모드 (GUI 없음)")
    args = parser.parse_args()

    crawler = InstagramBrowserCrawler(headless=args.headless, slow_mo=300)

    try:
        if not crawler.login():
            logger.error("로그인 실패! .env 크레덴셜을 확인하세요.")
            sys.exit(1)

        logger.info("로그인 성공! '{}' 모드로 크롤링 시작...", args.mode)

        if args.mode == "test":
            # 빠른 테스트: 해시태그 2개, 검색 1개, 소스당 10개
            stats = crawler.bulk_crawl(
                hashtags=TARGET_HASHTAGS[:2],
                search_keywords=SEARCH_KEYWORDS[:1],
                posts_per_source=10,
                crawl_explore=True,
                crawl_reels_feed=False,
            )

        elif args.mode == "users":
            stats = crawler.bulk_crawl(
                usernames=TARGET_USERS,
                posts_per_source=args.count,
                crawl_explore=False,
                crawl_reels_feed=False,
            )

        elif args.mode == "hashtags":
            stats = crawler.bulk_crawl(
                hashtags=TARGET_HASHTAGS,
                posts_per_source=args.count,
                crawl_explore=False,
                crawl_reels_feed=False,
            )

        elif args.mode == "search":
            stats = crawler.bulk_crawl(
                search_keywords=SEARCH_KEYWORDS,
                posts_per_source=args.count,
                crawl_explore=False,
                crawl_reels_feed=False,
            )

        elif args.mode == "explore":
            stats = crawler.bulk_crawl(
                posts_per_source=args.count,
                crawl_explore=True,
                crawl_reels_feed=False,
            )

        elif args.mode == "reels":
            stats = crawler.bulk_crawl(
                posts_per_source=args.count,
                crawl_explore=False,
                crawl_reels_feed=True,
            )

        elif args.mode == "full":
            stats = crawler.bulk_crawl(
                usernames=TARGET_USERS,
                hashtags=TARGET_HASHTAGS,
                search_keywords=SEARCH_KEYWORDS,
                posts_per_source=args.count,
                crawl_explore=True,
                crawl_reels_feed=True,
            )

        # 결과 요약
        print("\n" + "=" * 50)
        print("크롤링 요약")
        print("=" * 50)
        for k, v in stats.items():
            print(f"  {k}: {v}")

        # 파일 정보
        raw_dir = PROJECT_ROOT / "data" / "raw"
        if raw_dir.exists():
            files = list(raw_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in files)
            print(f"\n  수집 파일 수: {len(files)}")
            print(f"  전체 크기: {total_size / 1024:.1f} KB")

    finally:
        crawler.close()


if __name__ == "__main__":
    main()
