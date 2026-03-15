#!/usr/bin/env python3
"""대량 크롤링 스크립트 — GraphQL 인터셉트 방식으로 다양한 카테고리 수집."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.browser_crawler import InstagramBrowserCrawler
from src.utils.logger import get_logger

logger = get_logger()

# ── 카테고리별 해시태그 ──────────────────────────────────
HASHTAGS = {
    "패션/OOTD": [
        "ootd", "데일리룩", "오오티디", "패션스타그램", "코디추천",
        "봄코디", "겨울코디", "데일리코디", "셀스타그램", "옷스타그램",
        "스타일", "미니멀룩", "캐주얼룩", "출근룩", "퇴근룩",
        "오늘뭐입지", "패션", "룩북", "쇼핑", "자라",
    ],
    "카페/커피": [
        "카페스타그램", "카페투어", "서울카페", "카페추천", "커피스타그램",
        "카페", "브런치카페", "디저트카페", "감성카페", "카페맛집",
        "라떼", "아메리카노", "핸드드립", "홈카페", "카페인",
        "베이커리카페", "루프탑카페", "숨은카페", "뚝섬카페", "성수카페",
    ],
    "음식/맛집": [
        "맛집스타그램", "먹스타그램", "서울맛집", "맛집추천", "푸드스타그램",
        "점심메뉴", "저녁메뉴", "혼밥", "맛집탐방", "디저트",
        "브런치", "파스타", "스시", "한식", "양식",
        "홍대맛집", "강남맛집", "이태원맛집", "성수맛집", "을지로맛집",
    ],
    "여행/나들이": [
        "여행스타그램", "국내여행", "서울여행", "제주여행", "부산여행",
        "여행", "나들이", "피크닉", "한강", "산책",
        "일출", "바다", "캠핑", "글램핑", "드라이브",
        "강릉여행", "경주여행", "전주여행", "속초여행", "양양",
    ],
    "일상/감성": [
        "일상스타그램", "감성스타그램", "일상", "데일리", "소확행",
        "하루", "오늘의기록", "감성", "무드", "분위기",
        "셀카", "셀피", "거울셀카", "자연광", "골든아워",
        "일기", "기록", "추억", "행복", "힐링",
    ],
    "뷰티/메이크업": [
        "뷰티스타그램", "메이크업", "오늘의메이크업", "립스틱", "스킨케어",
        "화장품추천", "데일리메이크업", "뷰티", "네일아트", "헤어스타일",
    ],
    "인테리어/라이프": [
        "인테리어", "홈스타그램", "집꾸미기", "원룸인테리어", "자취방",
        "플랜테리어", "미니멀라이프", "홈데코", "수납정리", "셀프인테리어",
    ],
}

POSTS_PER_TAG = 30  # 해시태그당 수집량


def main():
    all_tags = []
    for category, tags in HASHTAGS.items():
        all_tags.extend(tags)
    all_tags = list(dict.fromkeys(all_tags))  # 중복 제거

    print("=" * 60)
    print(f"  대량 크롤링 시작")
    print(f"  카테고리: {len(HASHTAGS)}개")
    print(f"  해시태그: {len(all_tags)}개")
    print(f"  해시태그당: {POSTS_PER_TAG}개")
    print(f"  예상 최대: ~{len(all_tags) * POSTS_PER_TAG}개")
    print("=" * 60)

    crawler = InstagramBrowserCrawler(headless=False, slow_mo=300)
    total_collected = 0
    category_stats = {}

    try:
        if not crawler.login():
            print("로그인 실패!")
            return

        for category, tags in HASHTAGS.items():
            cat_count = 0
            print(f"\n{'━' * 60}")
            print(f"  [{category}] — {len(tags)}개 해시태그")
            print(f"{'━' * 60}")

            for tag in tags:
                try:
                    results = crawler.crawl_hashtag_intercept(tag, max_posts=POSTS_PER_TAG)
                    cat_count += len(results)
                    total_collected += len(results)
                    if results:
                        print(f"    #{tag}: {len(results)}개 수집")
                    else:
                        print(f"    #{tag}: 0개")

                    # 해시태그 간 짧은 딜레이
                    time.sleep(2)

                except Exception as exc:
                    print(f"    #{tag}: 실패 - {str(exc)[:60]}")

            category_stats[category] = cat_count
            print(f"  [{category}] 소계: {cat_count}개")

    except KeyboardInterrupt:
        print("\n\n  사용자에 의해 중단됨")
    finally:
        crawler.close()

    # 최종 요약
    print("\n" + "=" * 60)
    print("  크롤링 완료")
    print("=" * 60)
    for cat, count in category_stats.items():
        print(f"    {cat}: {count}개")
    print(f"\n  총 수집: {total_collected}개")

    # 학습 데이터 변환
    print("\n  학습 데이터로 변환 중...")
    from src.data_pipeline.cycle_pipeline import convert_crawled_to_training
    path, total = convert_crawled_to_training()
    print(f"  변환 완료: {total}개 샘플 → {path}")


if __name__ == "__main__":
    main()
