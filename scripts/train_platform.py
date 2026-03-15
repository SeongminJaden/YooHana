#!/usr/bin/env python3
"""플랫폼별(Instagram/Threads) 모델 학습 스크립트.

사용법:
    python3 scripts/train_platform.py instagram
    python3 scripts/train_platform.py threads
    python3 scripts/train_platform.py all
"""
from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

# GPU 메모리 최적화
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.cycle_pipeline import (
    convert_crawled_to_training,
    build_platform_datasets,
)

logger = get_logger()

_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def train_for_platform(platform: str, dataset_path: Path) -> None:
    """특정 플랫폼용 어댑터를 학습."""
    import torch
    import yaml
    from datasets import load_from_disk
    from src.training.train_qlora import _train_with_peft, _load_config

    cfg = _load_config(_CONFIG_PATH)
    adapter_dir = PROJECT_ROOT / "models" / f"adapter_{platform}"
    output_dir = str(PROJECT_ROOT / "outputs" / f"training_{platform}")

    logger.info("=" * 50)
    logger.info("{} 모델 학습 시작", platform.upper())
    logger.info("  데이터셋: {}", dataset_path)
    logger.info("  어댑터 저장: {}", adapter_dir)
    logger.info("=" * 50)

    # Load dataset
    ds_dict = load_from_disk(str(dataset_path))
    dataset = ds_dict["train"]
    logger.info("Dataset loaded: {} examples", len(dataset))

    # Override adapter path for this platform
    cfg_copy = {**cfg, "model": {**cfg["model"], "adapter_path": str(adapter_dir)}}

    # Clear GPU
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    max_seq_length = cfg["model"].get("max_seq_length", 512)

    # Try training with fallback
    fallback_configs = [
        {"seq_len": max_seq_length, "model": cfg["model"]["base_model"]},
        {"seq_len": max_seq_length, "model": cfg["model"]["fallback_model"]},
        {"seq_len": 256, "model": cfg["model"]["fallback_model"]},
    ]

    for i, fb in enumerate(fallback_configs):
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            cfg_try = {**cfg_copy, "model": {**cfg_copy["model"], "base_model": fb["model"]}}
            _train_with_peft(cfg_try, dataset, fb["seq_len"], output_dir)

            logger.success(
                "{} 학습 완료! (model={}, seq_len={}, adapter={})",
                platform.upper(), fb["model"], fb["seq_len"], adapter_dir,
            )
            return

        except (torch.cuda.OutOfMemoryError, RuntimeError) as exc:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if i < len(fallback_configs) - 1:
                next_fb = fallback_configs[i + 1]
                logger.warning(
                    "OOM: {}. Retrying with model={}, seq_len={}",
                    str(exc)[:80], next_fb["model"], next_fb["seq_len"],
                )
            else:
                logger.error("All fallback configs failed for {}", platform)
                raise


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("instagram", "threads", "all"):
        print("사용법: python3 scripts/train_platform.py [instagram|threads|all]")
        sys.exit(1)

    target = sys.argv[1]

    # Step 1: 데이터 변환
    print("데이터 변환 중...")
    convert_crawled_to_training()

    # Step 2: 플랫폼별 데이터셋 빌드
    print("플랫폼별 데이터셋 빌드 중...")
    datasets = build_platform_datasets()

    if not datasets:
        print("학습 데이터가 없습니다!")
        sys.exit(1)

    print(f"빌드된 데이터셋: {list(datasets.keys())}")

    # Step 3: 학습
    platforms = list(datasets.keys()) if target == "all" else [target]

    for platform in platforms:
        if platform not in datasets:
            print(f"  {platform} 데이터셋 없음, 건너뜀")
            continue

        train_for_platform(platform, datasets[platform])

        # GPU 메모리 정리 (다음 플랫폼 학습 전)
        import gc, torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print(f"\n  {platform} 학습 완료!\n")

    print("\n모든 학습 완료!")
    print("  어댑터 위치:")
    for p in platforms:
        print(f"    {p}: models/adapter_{p}/")


if __name__ == "__main__":
    main()
