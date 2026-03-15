#!/usr/bin/env python3
"""Threads 대량 크롤링 v2 — 목표 2만개."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.threads_crawler import ThreadsCrawler

KEYWORDS = [
    # ── 일상/감성 ──
    "일상", "오늘 하루", "소확행", "감성", "기록", "일기",
    "요즘 드는 생각", "주말", "퇴근 후", "혼자만의 시간",
    "오늘의 기분", "하루 정리", "새벽감성", "밤감성", "비오는날",
    "월요병", "금요일", "주말 뭐하지", "심심할때", "무기력",
    "잡생각", "새해", "봄", "여름", "가을", "겨울",
    "벚꽃", "단풍", "눈오는날", "따뜻한 하루",
    "오늘도 수고했어", "화이팅", "좋은 하루", "감사",
    "행복", "위로", "응원", "힐링", "성장", "도전",
    # ── 카페/음식 ──
    "카페", "카페 추천", "맛집", "디저트", "브런치",
    "커피", "혼밥", "오늘 뭐 먹지", "맛집 추천", "베이커리",
    "라떼", "아메리카노", "홈카페", "카페 투어", "디저트 맛집",
    "서울 카페", "부산 카페", "제주 카페", "성수 카페", "연남동 카페",
    "이태원 맛집", "홍대 맛집", "강남 맛집", "을지로 맛집",
    "파스타", "스시", "한식", "양식", "중식", "분식",
    "떡볶이", "치킨", "피자", "라면", "김밥", "국밥",
    "맥주", "와인", "칵테일", "술집 추천", "이자카야",
    "다이어트 식단", "건강식", "샐러드", "비건", "채식",
    "홈쿡", "자취 요리", "편의점 추천", "간식", "야식",
    # ── 패션/뷰티 ──
    "ootd", "오늘 코디", "데일리룩", "봄 코디", "여름 코디",
    "가을 코디", "겨울 코디", "쇼핑", "패션", "스타일",
    "옷 추천", "미니멀룩", "출근룩", "퇴근룩", "캐주얼",
    "스트릿패션", "빈티지", "유니클로", "자라", "무신사",
    "메이크업", "스킨케어", "화장품 추천", "네일", "헤어",
    "향수", "향수 추천", "립스틱", "쿠션", "선크림",
    "다이어트", "운동", "필라테스", "요가", "러닝",
    "헬스", "홈트", "몸매 관리", "체중 감량", "근력 운동",
    # ── 여행/나들이 ──
    "여행", "국내여행", "제주 여행", "부산 여행", "서울 나들이",
    "피크닉", "한강", "캠핑", "글램핑", "드라이브",
    "강릉 여행", "경주 여행", "전주 여행", "속초 여행", "양양",
    "해외여행", "일본 여행", "오사카", "도쿄", "방콕",
    "베트남 여행", "유럽 여행", "파리", "런던", "뉴욕",
    "비행기", "호텔", "에어비앤비", "숙소 추천", "여행 준비",
    "산책", "등산", "바다", "일출", "일몰",
    "사진 명소", "포토스팟", "뷰맛집", "루프탑", "야경",
    # ── 라이프스타일 ──
    "자취", "자취방", "원룸", "홈인테리어", "집꾸미기",
    "미니멀라이프", "정리정돈", "수납", "이사", "신혼집",
    "반려동물", "강아지", "고양이", "댕댕이", "냥이",
    "독서", "책 추천", "넷플릭스", "드라마 추천", "영화 추천",
    "음악", "플레이리스트", "콘서트", "페스티벌", "전시회",
    "취미", "그림", "사진", "캘리그라피", "뜨개질",
    "게임", "닌텐도", "플레이스테이션", "보드게임", "퍼즐",
    # ── 관계/감정 ──
    "연애", "썸", "이별", "짝사랑", "커플",
    "친구", "우정", "베프", "동창", "모임",
    "가족", "엄마", "아빠", "부모님", "형제",
    "직장생활", "회사", "퇴사", "이직", "면접",
    "스트레스", "번아웃", "고민", "불안", "우울",
    "mbti", "성격", "자존감", "마인드셋", "루틴",
    # ── 트렌드/문화 ──
    "요즘 유행", "밈", "트렌드", "핫플", "핫플레이스",
    "팝업스토어", "신상", "리뷰", "언박싱", "하울",
    "아이돌", "케이팝", "덕질", "굿즈", "앨범",
    "유튜브", "틱톡", "인스타", "블로그", "브이로그",
]

POSTS_PER_KEYWORD = 50


def main():
    total_keywords = len(KEYWORDS)
    print("=" * 60)
    print(f"  Threads 대량 크롤링 v2")
    print(f"  키워드: {total_keywords}개")
    print(f"  키워드당: {POSTS_PER_KEYWORD}개")
    print(f"  예상 최대: ~{total_keywords * POSTS_PER_KEYWORD}개")
    print(f"  목표: 20,000개")
    print("=" * 60)

    crawler = ThreadsCrawler(headless=False, slow_mo=300)
    total_collected = 0

    try:
        if not crawler.login():
            print("로그인 실패!")
            return

        for i, kw in enumerate(KEYWORDS):
            try:
                results = crawler.search_and_collect(kw, max_posts=POSTS_PER_KEYWORD)
                total_collected += len(results)

                if results:
                    print(f"  [{i+1}/{total_keywords}] '{kw}': {len(results)}개 (누적: {total_collected})")
                else:
                    print(f"  [{i+1}/{total_keywords}] '{kw}': 0개")

                # 목표 달성 시 조기 종료
                if total_collected >= 20000:
                    print(f"\n  목표 20,000개 달성! (실제: {total_collected})")
                    break

            except Exception as exc:
                print(f"  [{i+1}/{total_keywords}] '{kw}': 실패 - {str(exc)[:60]}")

    except KeyboardInterrupt:
        print("\n\n  사용자에 의해 중단됨")
    finally:
        crawler.close()

    print(f"\n  총 수집: {total_collected}개")


if __name__ == "__main__":
    main()
