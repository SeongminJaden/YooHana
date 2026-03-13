#!/usr/bin/env python3
"""Test caption and hashtag generation with the fine-tuned model."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.inference.text_generator import TextGenerator

logger = get_logger()


def main():
    logger.info("=== 캡션 생성 테스트 ===")

    gen = TextGenerator()

    # 테스트 주제들
    topics = [
        "카페 탐방",
        "봄 데일리룩",
        "서울 산책",
        "맛집 추천",
    ]

    for topic in topics:
        logger.info("--- 주제: {} ---", topic)

        # 캡션 생성
        caption = gen.generate_caption(topic=topic)
        print(f"\n📝 주제: {topic}")
        print(f"📄 캡션:\n{caption}")

        # 해시태그 제안 (persona 기반 규칙)
        hashtags = gen._persona.get_hashtags(topic)
        print(f"#️⃣  해시태그: {' '.join(hashtags)}")
        print("-" * 50)

    # 댓글 답글 테스트
    logger.info("=== 댓글 답글 테스트 ===")
    test_comments = [
        "언니 너무 예뻐요! 어디 카페에요?",
        "옷 정보 알려주세요~",
        "좋은 하루 되세요 ☀️",
    ]

    for comment in test_comments:
        reply = gen.generate_reply(comment=comment, post_caption="오늘 새로 발견한 카페 ☕ 분위기 너무 좋아")
        print(f"\n💬 댓글: {comment}")
        print(f"↩️  답글: {reply}")
        print("-" * 50)


if __name__ == "__main__":
    main()
