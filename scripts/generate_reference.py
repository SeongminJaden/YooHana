#!/usr/bin/env python3
"""Generate character reference images for consistent image generation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.persona.character import Persona
from src.image_gen.gemini_client import GeminiImageClient
from src.image_gen.prompt_composer import ImagePromptComposer
from src.image_gen.image_processor import ImageProcessor

logger = get_logger()

# Reference scenes for character consistency
REFERENCE_SCENES = [
    {"scene": "standing in a bright cafe, smiling naturally, half-body shot", "mood": "bright"},
    {"scene": "walking down a Seoul street in autumn, full-body shot", "mood": "golden hour"},
    {"scene": "sitting at a table reading a book, close-up portrait", "mood": "soft pastel"},
    {"scene": "posing in front of cherry blossoms in spring, three-quarter shot", "mood": "bright"},
    {"scene": "casual selfie-style photo at home, natural light from window", "mood": "soft pastel"},
    {"scene": "standing at a rooftop overlooking Seoul cityscape, golden hour", "mood": "golden hour"},
    {"scene": "sitting in a cozy winter cafe with a latte, warm lighting", "mood": "warm"},
    {"scene": "outdoor portrait in a park, natural sunlight, gentle smile", "mood": "bright"},
]


def main():
    parser = argparse.ArgumentParser(description="Generate character reference images")
    parser.add_argument(
        "--count",
        type=int,
        default=8,
        help="Number of reference images to generate",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(PROJECT_ROOT / "data" / "reference_images"),
        help="Output directory for reference images",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    persona = Persona()
    client = GeminiImageClient()
    composer = ImagePromptComposer(persona)
    processor = ImageProcessor()

    count = min(args.count, len(REFERENCE_SCENES))
    logger.info(f"Generating {count} reference images...")

    generated = []
    for i, scene_info in enumerate(REFERENCE_SCENES[:count]):
        logger.info(f"[{i+1}/{count}] Generating: {scene_info['scene'][:50]}...")

        prompt = composer.compose_feed_prompt(
            scene=scene_info["scene"],
            mood=scene_info["mood"],
        )

        try:
            # Use existing references for consistency (after first 2 images)
            refs = generated[:3] if len(generated) >= 2 else None
            image_data = client.generate_image(prompt, reference_images=refs)

            filename = f"reference_{i+1:02d}.png"
            saved_path = client.save_image(image_data, filename, str(output_dir))

            # Also create a feed-sized version
            processor.resize_for_feed(saved_path)

            generated.append(saved_path)
            logger.info(f"  Saved: {saved_path}")

        except Exception as e:
            logger.error(f"  Failed to generate image {i+1}: {e}")
            continue

    logger.info(f"Generated {len(generated)}/{count} reference images in {output_dir}")
    logger.info("Review the images and delete any that don't match the character well.")


if __name__ == "__main__":
    main()
