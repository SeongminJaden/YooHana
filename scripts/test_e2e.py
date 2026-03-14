#!/usr/bin/env python3
"""E2E 스모크 테스트 — 각 컴포넌트가 정상 동작하는지 검증.

실제 Instagram 포스팅은 하지 않음 (드라이런).

Usage:
    python3 scripts/test_e2e.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger

logger = get_logger()

PASS = "✓"
FAIL = "✗"
SKIP = "–"


def test_persona() -> bool:
    """페르소나 로드 및 프롬프트 생성 테스트."""
    try:
        from src.persona.character import Persona

        p = Persona()
        assert p.name == "유하나", f"이름 불일치: {p.name}"
        assert p.age == 24, f"나이 불일치: {p.age}"

        # 시스템 프롬프트
        sp = p.get_system_prompt()
        assert len(sp) > 100, f"시스템 프롬프트 너무 짧음: {len(sp)}"

        # 캡션 instruction
        ci = p.get_caption_instruction("카페 탐방")
        assert "카페" in ci

        # 답글 instruction
        ri = p.get_reply_instruction("너무 예뻐요!")
        assert "예뻐요" in ri

        # 이미지 프롬프트
        ip = p.get_image_prompt("sitting in a cafe")
        assert len(ip) > 50

        return True
    except Exception as e:
        logger.error("페르소나 테스트 실패: {}", e)
        return False


def test_topic_generator() -> bool:
    """주제/해시태그 생성 테스트."""
    try:
        from src.persona.character import Persona
        from src.planner.topic_generator import TopicGenerator

        p = Persona()
        tg = TopicGenerator(p)

        topics = tg.generate_topics(count=5)
        assert len(topics) >= 3, f"주제 부족: {len(topics)}"

        hashtags = tg.generate_hashtags(topics[0])
        assert len(hashtags) >= 3, f"해시태그 부족: {len(hashtags)}"
        assert all(h.startswith("#") for h in hashtags)

        seasonal = tg.get_seasonal_topics()
        assert len(seasonal) >= 1

        logger.info("  주제 예시: {}", topics[:3])
        logger.info("  해시태그 예시: {}", hashtags[:5])

        return True
    except Exception as e:
        logger.error("주제 생성 테스트 실패: {}", e)
        return False


def test_content_planner() -> bool:
    """주간 콘텐츠 기획 테스트."""
    try:
        from src.persona.character import Persona
        from src.planner.content_planner import ContentPlanner

        p = Persona()
        cp = ContentPlanner(text_generator=None, persona=p)

        plan = cp.generate_weekly_plan()
        assert len(plan) >= 7, f"기획 부족: {len(plan)}"

        for entry in plan:
            assert "topic" in entry
            assert "scene" in entry
            assert "hashtags" in entry
            assert "post_type" in entry

        logger.info("  기획 {}개 항목 생성", len(plan))
        logger.info("  Day1: {} ({})", plan[0]["topic"], plan[0]["post_type"])

        return True
    except Exception as e:
        logger.error("콘텐츠 기획 테스트 실패: {}", e)
        return False


def test_text_generator() -> bool:
    """LLM 텍스트 생성 테스트."""
    try:
        from src.inference.text_generator import TextGenerator

        gen = TextGenerator()

        # 캡션 생성
        caption = gen.generate_caption("오늘 카페에서 라떼 한 잔")
        assert len(caption) > 5, f"캡션 너무 짧음: '{caption}'"
        logger.info("  캡션: {}", caption[:80])

        # 답글 생성
        reply = gen.generate_reply("너무 예뻐요!", "오늘 성수동 카페 탐방 ☕")
        assert len(reply) > 3, f"답글 너무 짧음: '{reply}'"
        logger.info("  답글: {}", reply[:80])

        return True
    except FileNotFoundError:
        logger.warning("  모델 파일 없음 — 학습 필요")
        return False
    except Exception as e:
        logger.error("텍스트 생성 테스트 실패: {}", e)
        return False


def test_consistency_checker() -> bool:
    """페르소나 일관성 체커 테스트."""
    try:
        from src.persona.consistency import ConsistencyChecker

        checker = ConsistencyChecker()

        # 정상 텍스트
        ok_text = "오늘 카페에서 라떼 한 잔 ☕ 날씨도 좋고 기분도 좋다 ✨"
        is_valid, issues = checker.check_text(ok_text)
        logger.info("  정상 텍스트: valid={}, issues={}", is_valid, issues)

        return True
    except Exception as e:
        logger.error("일관성 체커 테스트 실패: {}", e)
        return False


def test_image_prompt_composer() -> bool:
    """이미지 프롬프트 조합 테스트."""
    try:
        from src.persona.character import Persona
        from src.image_gen.prompt_composer import ImagePromptComposer

        p = Persona()
        composer = ImagePromptComposer(p)

        prompt = composer.compose_feed_prompt(
            scene="sitting in a cafe", mood="bright"
        )
        assert len(prompt) > 50, f"프롬프트 너무 짧음: {len(prompt)}"
        logger.info("  프롬프트: {}...", prompt[:100])

        return True
    except Exception as e:
        logger.error("이미지 프롬프트 테스트 실패: {}", e)
        return False


def test_orchestrator_init() -> bool:
    """오케스트레이터 초기화 테스트 (스케줄 시작 안 함)."""
    try:
        from src.scheduler.orchestrator import Orchestrator

        orch = Orchestrator()

        assert orch.persona is not None, "Persona 미초기화"
        assert orch.content_planner is not None, "ContentPlanner 미초기화"
        assert orch.topic_generator is not None, "TopicGenerator 미초기화"

        logger.info("  Persona: {}", orch.persona.name)
        logger.info("  TextGenerator: {}", "OK" if orch.text_generator else "없음")
        logger.info("  ImageClient: {}", "OK" if orch.image_client else "없음")
        logger.info("  Poster: {}", "OK" if orch.poster else "없음")
        logger.info("  Commenter: {}", "OK" if orch.commenter else "없음")

        # Cleanup
        orch.stop()

        return True
    except Exception as e:
        logger.error("오케스트레이터 초기화 실패: {}", e)
        return False


def main() -> None:
    print()
    print("=" * 60)
    print("  AI Influencer E2E 스모크 테스트")
    print("=" * 60)
    print()

    tests = [
        ("페르소나", test_persona),
        ("주제 생성", test_topic_generator),
        ("콘텐츠 기획", test_content_planner),
        ("일관성 체커", test_consistency_checker),
        ("이미지 프롬프트", test_image_prompt_composer),
        ("LLM 텍스트 생성", test_text_generator),
        ("오케스트레이터 초기화", test_orchestrator_init),
    ]

    results = []
    for name, test_fn in tests:
        print(f"\n[{name}]")
        try:
            ok = test_fn()
            status = PASS if ok else FAIL
        except Exception as e:
            status = FAIL
            logger.error("  예외: {}", e)
        results.append((name, status))
        print(f"  결과: {status}")

    # Summary
    print()
    print("=" * 60)
    print("  결과 요약")
    print("=" * 60)
    for name, status in results:
        print(f"  {status} {name}")

    passed = sum(1 for _, s in results if s == PASS)
    total = len(results)
    print(f"\n  {passed}/{total} 통과")
    print()

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
