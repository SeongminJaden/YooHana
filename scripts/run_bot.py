#!/usr/bin/env python3
"""Main entry point - starts the AI Influencer bot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger

logger = get_logger()


def run_once():
    """Run a single posting cycle (useful for testing)."""
    from src.scheduler.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    logger.info("Running single posting cycle...")
    orchestrator.run_posting_cycle()
    logger.info("Single cycle complete.")


def run_comment_check():
    """Run a single comment check cycle."""
    from src.scheduler.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    logger.info("Running comment check...")
    orchestrator.run_comment_cycle()
    logger.info("Comment check complete.")


def run_daemon():
    """Start the full scheduler daemon."""
    from src.scheduler.orchestrator import Orchestrator

    logger.info("=" * 50)
    logger.info("AI Influencer Bot Starting")
    logger.info("=" * 50)

    orchestrator = Orchestrator()
    orchestrator.start()


def run_trend_analysis():
    """Run a single trend analysis and reel creation cycle."""
    from src.scheduler.orchestrator import Orchestrator

    orchestrator = Orchestrator()
    logger.info("Running trend analysis cycle...")
    orchestrator.run_trend_analysis_cycle()
    logger.info("Trend analysis cycle complete.")


def dry_run():
    """Test all components without actually posting."""
    from src.persona.character import Persona
    from src.planner.topic_generator import TopicGenerator

    logger.info("=== Dry Run: Testing Components ===")

    # Test persona
    logger.info("1. Testing Persona...")
    persona = Persona()
    logger.info(f"   Name: {persona.name}")
    logger.info(f"   System prompt length: {len(persona.get_system_prompt())} chars")

    # Test topic generation
    logger.info("2. Testing Topic Generator...")
    topic_gen = TopicGenerator(persona)
    topics = topic_gen.generate_topics(count=5)
    for t in topics:
        logger.info(f"   Topic: {t}")

    hashtags = topic_gen.generate_hashtags(topics[0])
    logger.info(f"   Hashtags for '{topics[0]}': {hashtags}")

    # Test image prompt composition
    logger.info("3. Testing Image Prompt Composer...")
    from src.image_gen.prompt_composer import ImagePromptComposer

    composer = ImagePromptComposer(persona)
    img_prompt = composer.compose_feed_prompt(
        scene="sitting in a cafe", mood="bright"
    )
    logger.info(f"   Image prompt: {img_prompt[:100]}...")

    # Test text generation (if model is available)
    logger.info("4. Testing Text Generator...")
    try:
        from src.inference.text_generator import TextGenerator

        gen = TextGenerator()
        caption = gen.generate_caption("카페에서 보낸 오후")
        logger.info(f"   Generated caption: {caption}")
    except Exception as e:
        logger.warning(f"   Text generator not available: {e}")
        logger.info("   (This is expected if the model hasn't been trained yet)")

    # Test consistency checker
    logger.info("5. Testing Consistency Checker...")
    from src.persona.consistency import ConsistencyChecker

    checker = ConsistencyChecker()
    test_text = "오늘 카페에서 라떼 한 잔 ☕ 날씨도 좋고 기분도 좋다 ✨"
    is_valid, issues = checker.check_text(test_text)
    logger.info(f"   Text valid: {is_valid}, Issues: {issues}")

    logger.info("=== Dry Run Complete ===")


def main():
    parser = argparse.ArgumentParser(description="AI Influencer Bot")
    parser.add_argument(
        "mode",
        choices=["start", "once", "comments", "trends", "dry-run"],
        help="Run mode: start (daemon), once (single post), comments (check comments), trends (trend analysis), dry-run (test)",
    )
    args = parser.parse_args()

    mode_map = {
        "start": run_daemon,
        "once": run_once,
        "comments": run_comment_check,
        "trends": run_trend_analysis,
        "dry-run": dry_run,
    }

    try:
        mode_map[args.mode]()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
