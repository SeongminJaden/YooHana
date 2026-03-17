#!/usr/bin/env python3
"""학습 데이터 품질 리포트 — 플랫폼별 분포, 길이, 키워드 분석."""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAINING_DIR = PROJECT_ROOT / "data" / "training"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# 불용어
STOPWORDS = {
    "그리고", "하지만", "그래서", "때문에", "이렇게", "저렇게", "그렇게",
    "너무", "정말", "진짜", "완전", "진심", "댓글", "좋아요", "팔로우",
    "모두", "보기", "사진", "동영상", "게시글", "게시물", "프로필",
    "이거", "저거", "그거", "여기", "저기", "거기", "이건", "저건",
    "오늘", "내일", "어제", "지금", "나는", "우리", "저는", "제가",
    "하는", "하고", "해서", "했는", "합니다", "합니당", "입니다",
    "있는", "없는", "같은", "이런", "저런", "한번", "아직",
    "광고", "협찬", "제공", "리뷰", "이벤트", "그냥", "이제",
}

# 스팸 패턴
SPAM_PATTERNS = [
    "문제가 발생하여", "페이지를 읽어들이지 못했습니다",
    "오류가 발생했습니다", "다시 시도해 주세요",
    "Something went wrong", "Page not found",
    "Sorry, this page isn't available",
]


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def detect_spam(records: list[dict]) -> list[dict]:
    spam = []
    for r in records:
        text = r.get("output", "")
        for p in SPAM_PATTERNS:
            if p in text:
                spam.append(r)
                break
    return spam


def length_stats(records: list[dict], field: str = "output") -> dict:
    lengths = [len(r.get(field, "")) for r in records]
    if not lengths:
        return {"count": 0}
    lengths.sort()
    return {
        "count": len(lengths),
        "min": lengths[0],
        "max": lengths[-1],
        "avg": round(sum(lengths) / len(lengths), 1),
        "median": lengths[len(lengths) // 2],
        "p10": lengths[int(len(lengths) * 0.1)],
        "p90": lengths[int(len(lengths) * 0.9)],
    }


def extract_keywords(records: list[dict], top_n: int = 20) -> list[tuple[str, int]]:
    counter: Counter = Counter()
    for r in records:
        text = unicodedata.normalize("NFC", r.get("output", ""))
        words = re.findall(r"[가-힣]{2,}", text)
        for w in words:
            if w not in STOPWORDS and len(w) >= 2:
                counter[w] += 1
    return counter.most_common(top_n)


def extract_hashtags(records: list[dict], top_n: int = 20) -> list[tuple[str, int]]:
    counter: Counter = Counter()
    for r in records:
        text = r.get("output", "")
        tags = re.findall(r"#([\w가-힣]+)", text)
        counter.update(tags)
    return counter.most_common(top_n)


def source_distribution(records: list[dict]) -> dict[str, int]:
    counter: Counter = Counter()
    for r in records:
        source = r.get("source", "unknown")
        # 카테고리 추출 (threads_카페_20260316 → threads)
        if source.startswith("threads"):
            counter["threads"] += 1
        elif source.startswith("hashtag"):
            counter["instagram:hashtag"] += 1
        elif source.startswith("bulk"):
            counter["instagram:bulk"] += 1
        elif source.startswith("explore"):
            counter["instagram:explore"] += 1
        elif source.startswith("search"):
            counter["instagram:search"] += 1
        else:
            counter[f"other:{source[:20]}"] += 1
    return dict(counter.most_common())


def duplicate_check(records: list[dict]) -> dict:
    texts = [r.get("output", "") for r in records]
    unique = set(texts)
    return {
        "total": len(texts),
        "unique": len(unique),
        "duplicates": len(texts) - len(unique),
        "dup_rate": round((len(texts) - len(unique)) / len(texts) * 100, 2) if texts else 0,
    }


def print_report():
    print("=" * 70)
    print("  학습 데이터 품질 리포트")
    print("=" * 70)

    # 1. 파일별 현황
    print("\n📁 학습 데이터 파일")
    print("-" * 50)
    files = {
        "crawled_captions.jsonl": "전체",
        "instagram_captions.jsonl": "Instagram",
        "threads_captions.jsonl": "Threads",
        "persona_captions_v3.jsonl": "페르소나 캡션",
        "persona_dialogues_v3.jsonl": "페르소나 대화",
        "persona_replies_v2.jsonl": "페르소나 답글",
    }
    for fname, label in files.items():
        p = TRAINING_DIR / fname
        if p.exists():
            count = sum(1 for _ in open(p))
            size_kb = p.stat().st_size / 1024
            print(f"  {label:20s} {count:>6,}건  ({size_kb:>8,.1f} KB)  {fname}")

    # 2. 플랫폼별 분석
    all_data = load_jsonl(TRAINING_DIR / "crawled_captions.jsonl")
    ig_data = load_jsonl(TRAINING_DIR / "instagram_captions.jsonl")
    th_data = load_jsonl(TRAINING_DIR / "threads_captions.jsonl")

    print(f"\n📊 플랫폼별 분포")
    print("-" * 50)
    print(f"  전체: {len(all_data):,}건")
    print(f"  Instagram: {len(ig_data):,}건 ({len(ig_data)/len(all_data)*100:.1f}%)" if all_data else "")
    print(f"  Threads:   {len(th_data):,}건 ({len(th_data)/len(all_data)*100:.1f}%)" if all_data else "")

    # 3. 소스 분포
    print(f"\n📡 수집 소스 분포")
    print("-" * 50)
    src_dist = source_distribution(all_data)
    for src, cnt in src_dist.items():
        print(f"  {src:25s} {cnt:>6,}건")

    # 4. 캡션 길이 분석
    print(f"\n📏 캡션 길이 분석")
    print("-" * 50)
    for label, data in [("전체", all_data), ("Instagram", ig_data), ("Threads", th_data)]:
        stats = length_stats(data)
        if stats["count"] == 0:
            continue
        print(f"  {label:12s} | 평균 {stats['avg']:>5.1f}자 | "
              f"중앙 {stats['median']:>4d}자 | "
              f"범위 {stats['min']}-{stats['max']}자 | "
              f"P10={stats['p10']} P90={stats['p90']}")

    # 5. 중복 분석
    print(f"\n🔄 중복 분석")
    print("-" * 50)
    for label, data in [("전체", all_data), ("Instagram", ig_data), ("Threads", th_data)]:
        dup = duplicate_check(data)
        print(f"  {label:12s} | 전체 {dup['total']:>6,} | "
              f"고유 {dup['unique']:>6,} | "
              f"중복 {dup['duplicates']:>4} ({dup['dup_rate']:.1f}%)")

    # 6. 스팸 감지
    print(f"\n🚫 스팸/오염 데이터")
    print("-" * 50)
    spam = detect_spam(all_data)
    print(f"  감지된 스팸: {len(spam)}건 / {len(all_data):,}건 ({len(spam)/len(all_data)*100:.2f}%)" if all_data else "")
    if spam:
        print(f"  샘플:")
        for s in spam[:5]:
            print(f"    - \"{s.get('output', '')[:60]}...\"")

    # 7. Top 키워드
    print(f"\n🔑 Top 20 키워드")
    print("-" * 50)
    for label, data in [("전체", all_data), ("Threads", th_data)]:
        kw = extract_keywords(data, top_n=20)
        if not kw:
            continue
        print(f"  [{label}]")
        line = "    "
        for word, cnt in kw:
            entry = f"{word}({cnt}) "
            if len(line) + len(entry) > 70:
                print(line)
                line = "    "
            line += entry
        if line.strip():
            print(line)

    # 8. Top 해시태그
    print(f"\n#️ Top 20 해시태그")
    print("-" * 50)
    tags = extract_hashtags(all_data, top_n=20)
    if tags:
        line = "    "
        for tag, cnt in tags:
            entry = f"#{tag}({cnt}) "
            if len(line) + len(entry) > 70:
                print(line)
                line = "    "
            line += entry
        if line.strip():
            print(line)

    # 9. Raw 데이터 현황
    print(f"\n📦 Raw 데이터 현황")
    print("-" * 50)
    raw_files = list(RAW_DIR.glob("*.json"))
    ig_raw = [f for f in raw_files if not f.name.startswith("threads_")]
    th_raw = [f for f in raw_files if f.name.startswith("threads_")]
    print(f"  전체 파일: {len(raw_files)}개")
    print(f"  Instagram: {len(ig_raw)}개")
    print(f"  Threads:   {len(th_raw)}개")

    total_raw = 0
    for f in raw_files:
        try:
            total_raw += len(json.load(open(f)))
        except Exception:
            pass
    print(f"  전체 raw 포스트: {total_raw:,}개")
    print(f"  변환률: {len(all_data)/total_raw*100:.1f}% ({len(all_data):,}/{total_raw:,})" if total_raw else "")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    print_report()
