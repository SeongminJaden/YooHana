#!/usr/bin/env python3
"""Trend analysis script - analyze trending reels/posts and create content."""
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

logger = get_logger()


def analyze_only(count: int = 20):
    """Scrape and analyze trends without posting."""
    from src.trend_analyzer.scraper import TrendScraper
    from src.trend_analyzer.media_analyzer import MediaAnalyzer
    from src.trend_analyzer.trend_detector import TrendDetector
    from src.persona.character import Persona

    scraper = TrendScraper()
    analyzer = MediaAnalyzer()
    detector = TrendDetector()
    persona = Persona()

    # Step 1: Scrape
    logger.info("=== Scraping {} trending items ===", count)
    reels = scraper.get_trending_reels(count=count)
    posts = scraper.get_trending_posts(count=count)
    all_items = reels + posts
    logger.info("Found {} reels, {} posts", len(reels), len(posts))

    # Step 2: Rank by engagement
    ranked = detector.rank_by_engagement(all_items)
    logger.info("\n=== Top 10 by engagement ===")
    for i, item in enumerate(ranked[:10]):
        logger.info(
            "  {}. {} | likes={} views={} | @{} | {}",
            i + 1,
            item.get("media_type", "?"),
            item.get("likes", 0),
            item.get("views", 0),
            item.get("user", "?"),
            (item.get("caption", "")[:60] + "...") if item.get("caption") else "(no caption)",
        )

    # Step 3: Analyze top items
    logger.info("\n=== Analyzing top 5 items ===")
    analyses = []
    for item in ranked[:5]:
        analysis = {"metadata": item}
        media_id = item.get("media_id", "")

        if item.get("media_type") == "reel":
            try:
                video_path = scraper.download_reel(media_id)
                if video_path:
                    full = analyzer.full_analysis(video_path, item.get("caption", ""))
                    analysis.update(full)
                    logger.info("  Analyzed reel {}: duration={}s, has_voice={}, has_music={}",
                               media_id,
                               full.get("video", {}).get("duration", "?"),
                               full.get("audio", {}).get("has_voice", "?"),
                               full.get("audio", {}).get("has_music", "?"))
            except Exception as e:
                logger.warning("  Failed to analyze reel {}: {}", media_id, e)
        else:
            try:
                caption_info = analyzer.analyze_caption_style(item.get("caption", ""))
                analysis["caption_analysis"] = caption_info
                thumb_path = scraper.download_thumbnail(media_id)
                if thumb_path:
                    analysis["visual"] = analyzer.analyze_thumbnail(thumb_path)
            except Exception as e:
                logger.warning("  Failed to analyze post {}: {}", media_id, e)

        analyses.append(analysis)

    # Step 4: Detect patterns
    logger.info("\n=== Pattern Detection ===")
    patterns = detector.detect_patterns(analyses)

    trending_audio = detector.get_trending_audio_ids(all_items)
    if trending_audio:
        logger.info("Trending audio tracks:")
        for audio in trending_audio[:5]:
            logger.info("  - {} (used {} times)", audio.get("name", "?"), audio.get("count", 0))

    # Step 5: Generate content brief
    brief = detector.generate_content_brief(patterns, persona)
    logger.info("\n=== Generated Content Brief ===")
    logger.info(json.dumps(brief, ensure_ascii=False, indent=2))

    # Save results
    output_path = PROJECT_ROOT / "data" / "trend_analysis_latest.json"
    results = {
        "trending_items": len(all_items),
        "patterns": patterns,
        "brief": brief,
        "trending_audio": trending_audio[:5] if trending_audio else [],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    logger.info("\nResults saved to {}", output_path)


def create_reel(brief_path: str = None):
    """Create a reel from a trend analysis brief."""
    from src.trend_analyzer.reel_creator import ReelCreator
    from src.trend_analyzer.trend_detector import TrendDetector
    from src.persona.character import Persona

    persona = Persona()

    # Load brief
    if brief_path:
        with open(brief_path) as f:
            data = json.load(f)
        brief = data.get("brief", data)
    else:
        latest = PROJECT_ROOT / "data" / "trend_analysis_latest.json"
        if not latest.exists():
            logger.error("No trend analysis found. Run 'analyze' first.")
            return
        with open(latest) as f:
            data = json.load(f)
        brief = data.get("brief", {})

    logger.info("=== Creating reel from brief ===")
    logger.info("Topic: {}", brief.get("topic", "?"))

    # Initialize components (text gen may not be available)
    text_gen = None
    image_client = None
    try:
        from src.inference.text_generator import TextGenerator
        text_gen = TextGenerator()
    except Exception as e:
        logger.warning("TextGenerator not available: {}", e)

    try:
        from src.image_gen.gemini_client import GeminiImageClient
        image_client = GeminiImageClient()
    except Exception as e:
        logger.warning("GeminiImageClient not available: {}", e)

    creator = ReelCreator(persona, text_gen, image_client)
    content = creator.create_reel_content(brief)

    if content and content.get("frames"):
        patterns = data.get("patterns", {})
        duration = creator.get_optimal_duration(patterns)
        video_path = creator.compose_reel_video(content["frames"], duration=duration)
        logger.info("Reel created: {}", video_path)
        logger.info("Caption: {}", content.get("caption", ""))
        logger.info("Hashtags: {}", content.get("hashtags", []))
    else:
        logger.error("Failed to create reel content")


def main():
    parser = argparse.ArgumentParser(description="Trend Analysis & Reel Creator")
    parser.add_argument(
        "mode",
        choices=["analyze", "create-reel", "full"],
        help="Mode: analyze (scrape+analyze), create-reel (from saved brief), full (analyze+create)",
    )
    parser.add_argument("--count", type=int, default=20, help="Number of items to scrape")
    parser.add_argument("--brief", type=str, default=None, help="Path to brief JSON for create-reel")
    args = parser.parse_args()

    if args.mode in ("analyze", "full"):
        analyze_only(count=args.count)

    if args.mode in ("create-reel", "full"):
        create_reel(brief_path=args.brief)


if __name__ == "__main__":
    main()
