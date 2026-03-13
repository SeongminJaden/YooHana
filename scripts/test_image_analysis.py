#!/usr/bin/env python3
"""Test image analysis and NanoBanana prompt generation (no API calls)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger
from src.image_gen.image_analyzer import ImageAnalyzer

logger = get_logger()


def main():
    logger.info("=== 이미지 분석 + 나노바나나 프롬프트 생성 테스트 ===")

    analyzer = ImageAnalyzer()

    # Analyze all crawled posts
    analyses = analyzer.analyze_all_posts()

    if not analyses:
        logger.error("분석할 이미지가 없습니다!")
        return

    # Save all analyses
    output_path = analyzer.save_analyses(analyses)
    logger.info("분석 결과 저장: {}", output_path)

    # Show sample results
    print(f"\n총 {len(analyses)}개 이미지 분석 완료\n")
    print("=" * 60)

    for i, a in enumerate(analyses[:5]):
        print(f"\n[{i+1}] @{a['username']} ({a['media_type']})")
        print(f"  의상: {a['clothing']}")
        print(f"  포즈: {a['pose']}")
        print(f"  표정: {a['expression']}")
        print(f"  배경: {a['background']}")
        print(f"  조명: {a['lighting']}")
        print(f"  분위기: {a['mood']}")

        nb = a.get("nanobana_prompt", {})
        if nb:
            print(f"\n  [NanoBanana 캐릭터 프롬프트]")
            print(f"  {nb['character_prompt'][:200]}...")
            print(f"\n  [NanoBanana 배경 프롬프트]")
            print(f"  {nb['background_prompt'][:200]}...")
        print("-" * 60)

    # Statistics
    clothing_dist: dict[str, int] = {}
    mood_dist: dict[str, int] = {}
    for a in analyses:
        clothing_dist[a["clothing"]] = clothing_dist.get(a["clothing"], 0) + 1
        mood_dist[a["mood"]] = mood_dist.get(a["mood"], 0) + 1

    print("\n=== 의상 분포 ===")
    for k, v in sorted(clothing_dist.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k}: {v}")

    print("\n=== 분위기 분포 ===")
    for k, v in sorted(mood_dist.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
