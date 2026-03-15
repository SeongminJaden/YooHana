#!/usr/bin/env python3
"""Threads 대량 크롤링 스크립트."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.threads_crawler import ThreadsCrawler

KEYWORDS = [
    # 일상/감성
    "일상", "오늘 하루", "소확행", "혼자만의 시간", "감성",
    "기록", "일기", "요즘 드는 생각", "주말", "퇴근 후",
    # 카페/음식
    "카페", "카페 추천", "맛집", "디저트", "브런치",
    "커피", "혼밥", "오늘 뭐 먹지", "서울 맛집", "베이커리",
    # 패션
    "ootd", "오늘 코디", "데일리룩", "봄 코디", "쇼핑",
    "패션", "스타일", "옷 추천", "미니멀룩", "출근룩",
    # 여행
    "여행", "국내여행", "제주", "부산", "서울 나들이",
    "피크닉", "한강", "캠핑", "힐링", "산책",
    # 뷰티
    "메이크업", "스킨케어", "화장품 추천", "네일", "헤어",
    # 라이프스타일
    "자취", "홈카페", "인테리어", "집꾸미기", "미니멀라이프",
    "운동", "필라테스", "러닝", "다이어트", "건강",
    # 관계/감정
    "연애", "친구", "우정", "가족", "고민",
    "위로", "응원", "행복", "감사", "성장",
]

POSTS_PER_KEYWORD = 20


def main():
    print("=" * 60)
    print(f"  Threads 대량 크롤링")
    print(f"  키워드: {len(KEYWORDS)}개")
    print(f"  키워드당: {POSTS_PER_KEYWORD}개")
    print(f"  예상 최대: ~{len(KEYWORDS) * POSTS_PER_KEYWORD}개")
    print("=" * 60)

    crawler = ThreadsCrawler(headless=False, slow_mo=300)
    try:
        if not crawler.login():
            print("로그인 실패!")
            return

        stats = crawler.bulk_search(KEYWORDS, posts_per_keyword=POSTS_PER_KEYWORD)

        print("\n" + "=" * 60)
        print("  Threads 크롤링 완료")
        print("=" * 60)
        total = sum(stats.values())
        for kw, cnt in stats.items():
            if cnt > 0:
                print(f"    '{kw}': {cnt}개")
        print(f"\n  총 수집: {total}개")

        # 학습 데이터 변환
        print("\n  학습 데이터로 변환 중...")
        from src.data_pipeline.cycle_pipeline import convert_crawled_to_training
        path, total_samples = convert_crawled_to_training()
        print(f"  변환 완료: {total_samples}개 샘플 → {path}")

    finally:
        crawler.close()


if __name__ == "__main__":
    main()
