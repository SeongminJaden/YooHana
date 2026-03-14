#!/usr/bin/env python3
"""Generate persona-style training data using Gemini API."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.persona_data_generator import PersonaDataGenerator

logger = get_logger()


def main():
    parser = argparse.ArgumentParser(description="Generate persona training data")
    parser.add_argument("--captions", type=int, default=50,
                        help="Number of crawled captions to convert")
    parser.add_argument("--replies", type=int, default=50,
                        help="Number of comment-reply pairs to generate")
    parser.add_argument("--originals", type=int, default=50,
                        help="Number of original captions to generate")
    parser.add_argument("--skip-convert", action="store_true",
                        help="Skip caption conversion step")
    parser.add_argument("--skip-replies", action="store_true",
                        help="Skip reply generation step")
    parser.add_argument("--skip-originals", action="store_true",
                        help="Skip original caption generation step")
    args = parser.parse_args()

    gen = PersonaDataGenerator()

    captions = []
    replies = []
    originals = []

    if not args.skip_convert:
        logger.info("=== 1. 크롤링 캡션 → 유하나 말투 변환 ({}) ===", args.captions)
        captions = gen.batch_convert_captions(limit=args.captions)
        logger.info("변환 완료: {}개", len(captions))

    if not args.skip_replies:
        logger.info("=== 2. 댓글 답글 쌍 생성 ({}) ===", args.replies)
        replies = gen.generate_comment_replies(count=args.replies)
        logger.info("생성 완료: {}개", len(replies))

    if not args.skip_originals:
        logger.info("=== 3. 오리지널 캡션 생성 ({}) ===", args.originals)
        originals = gen.generate_original_captions(count=args.originals)
        logger.info("생성 완료: {}개", len(originals))

    # Save all
    if captions or replies or originals:
        output = gen.save_all(captions, replies, originals)
        total = len(captions) + len(replies) + len(originals)
        logger.success("총 {}개 페르소나 학습 데이터 저장: {}", total, output)

        # Preview samples
        print("\n=== 샘플 미리보기 ===")
        if captions:
            print("\n[변환 캡션]")
            for c in captions[:3]:
                print(f"  Q: {c['instruction'][:60]}")
                print(f"  A: {c['output'][:80]}")
                print()
        if replies:
            print("[댓글 답글]")
            for r in replies[:3]:
                print(f"  Q: {r['instruction'][:80]}")
                print(f"  A: {r['output'][:60]}")
                print()
        if originals:
            print("[오리지널 캡션]")
            for o in originals[:3]:
                print(f"  Q: {o['instruction'][:60]}")
                print(f"  A: {o['output'][:80]}")
                print()
    else:
        logger.warning("No data generated!")


if __name__ == "__main__":
    main()
