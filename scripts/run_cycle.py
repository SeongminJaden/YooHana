#!/usr/bin/env python3
"""순환 파이프라인 실행 스크립트.

크롤링 → 학습 데이터 변환 → 키워드 추출 → 재학습 → 재크롤링
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.cycle_pipeline import (
    convert_crawled_to_training,
    extract_keywords_from_crawled,
    build_training_dataset,
    load_cycle_state,
    save_cycle_state,
    update_crawl_targets,
    run_cycle,
)

logger = get_logger()


def cmd_convert(args):
    """크롤링 데이터 → 학습 JSONL 변환만 실행."""
    path, count = convert_crawled_to_training()
    print(f"\n변환 완료: {count} 샘플 → {path}")


def cmd_keywords(args):
    """키워드 추출만 실행."""
    result = extract_keywords_from_crawled(top_n=args.top_n)

    print("\n" + "=" * 50)
    print("키워드 추출 결과")
    print("=" * 50)

    print("\n[해시태그]")
    for tag, cnt in result["hashtags"][:15]:
        print(f"  #{tag} ({cnt})")

    print("\n[키워드]")
    for word, cnt in result["keywords"][:15]:
        print(f"  {word} ({cnt})")

    print("\n[바이그램]")
    for bg, cnt in result["bigrams"][:10]:
        print(f"  {bg} ({cnt})")

    print("\n[새 크롤링 타겟]")
    for target in result["potential_targets"]:
        print(f"  [{target['type']}] {target['value']}")


def cmd_build(args):
    """HuggingFace Dataset 빌드만 실행."""
    path = build_training_dataset()
    print(f"\n데이터셋 빌드 완료: {path}")


def cmd_status(args):
    """순환 파이프라인 상태 조회."""
    state = load_cycle_state()

    print("\n" + "=" * 50)
    print("순환 파이프라인 상태")
    print("=" * 50)
    print(f"  사이클 횟수: {state['cycle_count']}")
    print(f"  총 학습 샘플: {state['total_samples']}")

    dh = state.get("discovered_hashtags", [])
    ds = state.get("discovered_searches", [])
    print(f"  발견된 해시태그: {len(dh)}개")
    for h in dh:
        print(f"    #{h}")
    print(f"  발견된 검색어: {len(ds)}개")
    for s in ds:
        print(f"    {s}")

    history = state.get("history", [])
    if history:
        print(f"\n  [히스토리]")
        for h in history[-5:]:
            print(f"    사이클 #{h['cycle']}: {h['date'][:10]} - {h['samples']} 샘플")


def cmd_full(args):
    """전체 순환 실행."""
    result = run_cycle(
        skip_crawl=args.skip_crawl,
        skip_train=args.skip_train,
        crawl_count=args.count,
        headless=args.headless,
    )

    print("\n" + "=" * 50)
    print("순환 결과")
    print("=" * 50)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(
        description="순환 파이프라인: 크롤링 ↔ 학습 ↔ 재크롤링"
    )
    sub = parser.add_subparsers(dest="command", help="실행할 명령")

    # convert
    sub.add_parser("convert", help="크롤링 데이터 → 학습 JSONL 변환")

    # keywords
    kw = sub.add_parser("keywords", help="키워드/해시태그 추출")
    kw.add_argument("--top-n", type=int, default=30, help="추출할 상위 키워드 수")

    # build
    sub.add_parser("build", help="HuggingFace Dataset 빌드")

    # status
    sub.add_parser("status", help="순환 상태 조회")

    # full (전체 순환)
    full = sub.add_parser("full", help="전체 순환 실행")
    full.add_argument("--skip-crawl", action="store_true", help="크롤링 건너뜀")
    full.add_argument("--skip-train", action="store_true", help="학습 건너뜀")
    full.add_argument("--count", type=int, default=20, help="소스당 수집 게시글 수")
    full.add_argument("--headless", action="store_true", help="헤드리스 모드")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "convert": cmd_convert,
        "keywords": cmd_keywords,
        "build": cmd_build,
        "status": cmd_status,
        "full": cmd_full,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
