#!/usr/bin/env python3
"""Threads 대량 크롤링 — 목표 10,000개.

기존 수집 데이터(~3,800개)에 추가하여 총 10,000개 달성을 목표로 한다.
이미 크롤링된 키워드는 건너뛰고, 데이터 품질 필터링을 적용한다.
완료 후 자동으로 학습 JSONL 변환까지 수행한다.
"""
from __future__ import annotations

import json
import glob
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.data_pipeline.threads_crawler import ThreadsCrawler

# ── 목표 설정 ──
TARGET_TOTAL = 10_000
POSTS_PER_KEYWORD = 60

# ── 전체 키워드 목록 (300+) ──────────────────────────────────────
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
    "혼자서도 괜찮아", "나만의 시간", "오늘 뭐했냐면",
    "마음 정리", "새벽 일기", "감사일기", "긍정", "루틴",

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
    "서울 맛집", "빵 맛집", "크로플", "마카롱", "케이크",
    "소금빵", "약과", "탕후루", "딸기 디저트", "봄 메뉴",
    "아이스크림", "빙수", "밀크티", "생과일주스",

    # ── 패션/뷰티 ──
    "ootd", "오늘 코디", "데일리룩", "봄 코디", "여름 코디",
    "가을 코디", "겨울 코디", "쇼핑", "패션", "스타일",
    "옷 추천", "미니멀룩", "출근룩", "퇴근룩", "캐주얼",
    "스트릿패션", "빈티지", "유니클로", "자라", "무신사",
    "메이크업", "스킨케어", "화장품 추천", "네일", "헤어",
    "향수", "향수 추천", "립스틱", "쿠션", "선크림",
    "다이어트", "운동", "필라테스", "요가", "러닝",
    "헬스", "홈트", "몸매 관리", "체중 감량", "근력 운동",
    "봄 신상", "트렌치코트", "가디건", "청바지", "스니커즈",
    "원피스", "반팔", "린넨", "레이어드", "컬러 매칭",

    # ── 여행/나들이 ──
    "여행", "국내여행", "제주 여행", "부산 여행", "서울 나들이",
    "피크닉", "한강", "캠핑", "글램핑", "드라이브",
    "강릉 여행", "경주 여행", "전주 여행", "속초 여행", "양양",
    "해외여행", "일본 여행", "오사카", "도쿄", "방콕",
    "베트남 여행", "유럽 여행", "파리", "런던", "뉴욕",
    "비행기", "호텔", "에어비앤비", "숙소 추천", "여행 준비",
    "산책", "등산", "바다", "일출", "일몰",
    "사진 명소", "포토스팟", "뷰맛집", "루프탑", "야경",
    "벚꽃 명소", "봄 나들이", "꽃 구경", "공원 산책", "자전거",
    "주말 나들이", "당일치기", "근교 여행", "서울 산책", "한옥마을",

    # ── 라이프스타일 ──
    "자취", "자취방", "원룸", "홈인테리어", "집꾸미기",
    "미니멀라이프", "정리정돈", "수납", "이사", "신혼집",
    "반려동물", "강아지", "고양이", "댕댕이", "냥이",
    "독서", "책 추천", "넷플릭스", "드라마 추천", "영화 추천",
    "음악", "플레이리스트", "콘서트", "페스티벌", "전시회",
    "취미", "그림", "사진", "캘리그라피", "뜨개질",
    "게임", "닌텐도", "플레이스테이션", "보드게임", "퍼즐",
    "식물", "플랜테리어", "다이소", "올리브영", "생활꿀팁",
    "아이패드", "갤럭시", "아이폰", "테크", "가젯",

    # ── 관계/감정 ──
    "연애", "썸", "이별", "짝사랑", "커플",
    "친구", "우정", "베프", "동창", "모임",
    "가족", "엄마", "아빠", "부모님", "형제",
    "직장생활", "회사", "퇴사", "이직", "면접",
    "스트레스", "번아웃", "고민", "불안", "우울",
    "mbti", "성격", "자존감", "마인드셋",
    "연애 고민", "솔로", "소개팅", "결혼", "동거",
    "인간관계", "거리두기", "혼자가 편해", "내향인", "외향인",

    # ── 트렌드/문화 ──
    "요즘 유행", "밈", "트렌드", "핫플", "핫플레이스",
    "팝업스토어", "신상", "리뷰", "언박싱", "하울",
    "아이돌", "케이팝", "덕질", "굿즈", "앨범",
    "유튜브", "틱톡", "인스타", "블로그", "브이로그",
    "챗GPT", "AI", "인공지능", "생산성", "사이드프로젝트",
    "주식", "부동산", "재테크", "절약", "저축",
    "자기계발", "공부", "영어공부", "코딩", "자격증",
    "N잡", "프리랜서", "디지털노마드", "원격근무", "부업",

    # ── 2026 봄 트렌드 ──
    "봄맞이", "봄옷", "봄 나들이", "벚꽃 시즌", "개나리",
    "봄 감성", "봄향기", "봄 청소", "새학기", "신학기",
    "졸업", "입학", "진학", "3월", "새출발",
    "날씨 좋은 날", "봄바람", "산책하기 좋은 날",
    "플리마켓", "벼룩시장", "봄 페스티벌", "축제",
    "텃밭", "가드닝", "꽃꽂이", "봄꽃",
    "알러지", "미세먼지", "환절기", "건강관리",

    # ── Threads 특화 (의견/토론형) ──
    "요즘 고민", "이거 나만 그래", "공감", "TMI", "질문",
    "추천해줘", "어떻게 생각해", "솔직히", "논쟁",
    "인생 조언", "현실", "공감되는", "찐",
    "별거 아닌데", "갑자기 궁금한", "혼잣말", "독백",
    "오늘의 한마디", "명언", "좌우명", "인생관",
    "이건 인정", "사실", "실화", "레전드",
    "처음 해봤는데", "요즘 빠진", "최근에 발견한",
    "꿀팁", "추천", "인생템", "인생 맛집", "인생 카페",
    "갓성비", "가성비", "추천 리스트", "위시리스트",
]

# 중복 제거
KEYWORDS = list(dict.fromkeys(KEYWORDS))

# ── 품질 필터 (오류 페이지/스팸 패턴) ──
SPAM_PATTERNS = [
    "문제가 발생하여",
    "페이지를 읽어들이지 못했습니다",
    "오류가 발생했습니다",
    "다시 시도해 주세요",
    "로그인이 필요합니다",
    "이 페이지는 사용할 수 없습니다",
    "콘텐츠를 이용할 수 없습니다",
    "Something went wrong",
    "Page not found",
    "Sorry, this page isn't available",
]


def _count_existing_posts() -> tuple[int, set[str]]:
    """기존 Threads raw 파일에서 포스트 수 및 크롤링된 키워드 확인."""
    files = glob.glob(str(PROJECT_ROOT / "data" / "raw" / "threads_*.json"))
    total = 0
    crawled_keywords = set()

    for f in files:
        m = re.search(r"threads_(.+?)_\d{8}_\d{6}", Path(f).stem)
        if m:
            crawled_keywords.add(m.group(1).replace("_", " "))
        try:
            with open(f) as fh:
                data = json.load(fh)
                total += len(data)
        except Exception:
            pass

    return total, crawled_keywords


def _is_spam(text: str) -> bool:
    """스팸/오류 텍스트 판별."""
    for pattern in SPAM_PATTERNS:
        if pattern in text:
            return True
    # 너무 짧거나 의미 없는 텍스트
    if len(text.strip()) < 10:
        return True
    # 순수 이모지/특수문자만
    cleaned = re.sub(r"[^\w가-힣a-zA-Z]", "", text)
    if len(cleaned) < 5:
        return True
    return False


def _post_crawl_quality_report(crawler: ThreadsCrawler) -> dict:
    """크롤링 후 데이터 품질 리포트."""
    all_posts = crawler.get_all_collected()
    total = len(all_posts)
    if total == 0:
        return {"total": 0, "valid": 0, "spam": 0, "rate": 0}

    spam_count = sum(1 for p in all_posts if _is_spam(p.get("caption", "")))
    valid = total - spam_count

    # 길이 분포
    lengths = [len(p.get("caption", "")) for p in all_posts]
    avg_len = sum(lengths) / len(lengths) if lengths else 0

    return {
        "total": total,
        "valid": valid,
        "spam": spam_count,
        "rate": round(valid / total * 100, 1) if total else 0,
        "avg_caption_len": round(avg_len, 1),
    }


def _convert_to_training():
    """크롤링 데이터를 학습 JSONL로 변환."""
    from src.data_pipeline.cycle_pipeline import convert_crawled_to_training

    output_path = PROJECT_ROOT / "data" / "training" / "threads_captions.jsonl"
    path, count = convert_crawled_to_training(
        raw_dir=PROJECT_ROOT / "data" / "raw",
        output_path=None,  # 기본 경로 사용 (crawled_captions.jsonl + 플랫폼별 분리)
    )
    print(f"\n  학습 데이터 변환 완료: {count}개 → {path}")


def main():
    existing_count, crawled_kw = _count_existing_posts()
    remaining_keywords = [kw for kw in KEYWORDS if kw not in crawled_kw]
    needed = max(0, TARGET_TOTAL - existing_count)

    print("=" * 60)
    print(f"  Threads 대량 크롤링 — 목표 {TARGET_TOTAL:,}개")
    print(f"  기존 수집: {existing_count:,}개")
    print(f"  추가 필요: {needed:,}개")
    print(f"  전체 키워드: {len(KEYWORDS)}개")
    print(f"  이미 크롤링: {len(crawled_kw)}개")
    print(f"  남은 키워드: {len(remaining_keywords)}개")
    print(f"  키워드당 목표: {POSTS_PER_KEYWORD}개")
    print(f"  예상 최대: ~{len(remaining_keywords) * POSTS_PER_KEYWORD:,}개")
    print("=" * 60)

    if needed <= 0:
        print(f"\n  이미 목표 달성! ({existing_count:,} >= {TARGET_TOTAL:,})")
        print("  학습 데이터 변환만 실행합니다...")
        _convert_to_training()
        return

    if not remaining_keywords:
        print("\n  크롤링할 키워드가 남아있지 않습니다.")
        _convert_to_training()
        return

    crawler = ThreadsCrawler(headless=False, slow_mo=300)
    total_new = 0
    failed_kw = []

    try:
        if not crawler.login():
            print("  로그인 실패!")
            return

        for i, kw in enumerate(remaining_keywords):
            try:
                results = crawler.search_and_collect(kw, max_posts=POSTS_PER_KEYWORD)

                # 스팸 필터링 통계
                valid = [r for r in results if not _is_spam(r.get("caption", ""))]
                spam = len(results) - len(valid)

                total_new += len(results)
                current_total = existing_count + total_new

                status = f"[{i+1}/{len(remaining_keywords)}]"
                if results:
                    print(f"  {status} '{kw}': {len(valid)}개 수집"
                          f"{f' (스팸 {spam}개 제외)' if spam else ''}"
                          f" — 누적: {current_total:,}/{TARGET_TOTAL:,}")
                else:
                    print(f"  {status} '{kw}': 0개")

                # 목표 달성 시 조기 종료
                if current_total >= TARGET_TOTAL:
                    print(f"\n  목표 {TARGET_TOTAL:,}개 달성! (실제: {current_total:,})")
                    break

            except Exception as exc:
                failed_kw.append(kw)
                print(f"  [{i+1}/{len(remaining_keywords)}] '{kw}': 실패 — {str(exc)[:80]}")

    except KeyboardInterrupt:
        print("\n\n  사용자에 의해 중단됨")
    finally:
        # 품질 리포트
        report = _post_crawl_quality_report(crawler)
        crawler.close()

    # ── 결과 요약 ──
    final_total = existing_count + total_new
    print("\n" + "=" * 60)
    print(f"  크롤링 완료!")
    print(f"  이번 수집: {total_new:,}개")
    print(f"  전체 누적: {final_total:,}개")
    if report.get("total"):
        print(f"  품질: 유효 {report['rate']}% (스팸 {report['spam']}개)")
        print(f"  평균 캡션 길이: {report['avg_caption_len']}자")
    if failed_kw:
        print(f"  실패 키워드: {len(failed_kw)}개")
    print("=" * 60)

    # ── 학습 데이터 변환 ──
    print("\n  학습 데이터 변환 중...")
    _convert_to_training()

    print("\n  완료!")


if __name__ == "__main__":
    main()
