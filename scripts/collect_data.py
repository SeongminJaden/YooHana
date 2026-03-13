#!/usr/bin/env python3
"""Data collection script - collects Instagram captions and prepares training data."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger
from src.data_pipeline.collector import CaptionCollector
from src.data_pipeline.cleaner import DataCleaner
from src.data_pipeline.dataset_builder import DatasetBuilder

logger = get_logger()


def main():
    parser = argparse.ArgumentParser(description="Collect and prepare training data")
    parser.add_argument(
        "--step",
        choices=["collect", "clean", "build", "all"],
        default="all",
        help="Which step to run",
    )
    parser.add_argument(
        "--usernames",
        nargs="*",
        default=[],
        help="Instagram usernames to collect from",
    )
    parser.add_argument(
        "--hashtags",
        nargs="*",
        default=["일상스타그램", "카페스타그램", "오오티디", "서울라이프"],
        help="Hashtags to collect from",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=50,
        help="Number of posts to collect per source",
    )
    args = parser.parse_args()

    data_dir = PROJECT_ROOT / "data"

    if args.step in ("collect", "all"):
        logger.info("=== Step 1: Collecting captions ===")
        collector = CaptionCollector()

        for username in args.usernames:
            logger.info(f"Collecting from @{username}...")
            collector.collect_from_user(username, count=args.count)

        for hashtag in args.hashtags:
            logger.info(f"Collecting from #{hashtag}...")
            collector.collect_from_hashtag(hashtag, count=args.count)

    if args.step in ("clean", "all"):
        logger.info("=== Step 2: Cleaning data ===")
        cleaner = DataCleaner()
        cleaner.process_all(
            input_dir=str(data_dir / "raw"),
            output_path=str(data_dir / "processed" / "cleaned_captions.jsonl"),
        )

    if args.step in ("build", "all"):
        logger.info("=== Step 3: Building HuggingFace dataset ===")
        builder = DatasetBuilder()

        # Build caption dataset
        captions_path = data_dir / "processed" / "cleaned_captions.jsonl"
        if captions_path.exists():
            caption_ds = builder.build_caption_dataset(
                str(captions_path), persona_name="유하나"
            )
            logger.info(f"Caption dataset: {len(caption_ds)} examples")

            # Build reply dataset if available
            replies_path = data_dir / "training" / "comments.jsonl"
            datasets_to_merge = [caption_ds]
            if replies_path.exists():
                reply_ds = builder.build_reply_dataset(str(replies_path))
                datasets_to_merge.append(reply_ds)
                logger.info(f"Reply dataset: {len(reply_ds)} examples")

            # Merge and split
            merged = builder.merge_datasets(datasets_to_merge)
            split = builder.split_train_val(merged)
            builder.save(split, "final_dataset")
            logger.info(
                f"Final dataset: {len(split['train'])} train, "
                f"{len(split['validation'])} val"
            )
        else:
            logger.warning(
                f"No cleaned captions found at {captions_path}. "
                "Run collect and clean steps first."
            )

    logger.info("=== Data pipeline complete ===")


if __name__ == "__main__":
    main()
