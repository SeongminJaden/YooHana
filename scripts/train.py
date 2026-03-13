#!/usr/bin/env python3
"""Training script - QLoRA fine-tuning and evaluation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.logger import get_logger

logger = get_logger()


def main():
    parser = argparse.ArgumentParser(description="Fine-tune LLM with QLoRA")
    parser.add_argument(
        "--step",
        choices=["train", "merge", "evaluate", "all"],
        default="all",
        help="Which step to run",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs",
    )
    parser.add_argument(
        "--resume",
        type=str,
        default=None,
        help="Resume training from checkpoint path",
    )
    args = parser.parse_args()

    if args.step in ("train", "all"):
        logger.info("=== Step 1: QLoRA Fine-tuning ===")
        from src.training.train_qlora import train

        train(num_epochs=args.epochs, resume_from=args.resume)

    if args.step in ("merge", "all"):
        logger.info("=== Step 2: Merging LoRA adapter ===")
        from src.training.merge_adapter import load_and_merge
        import yaml

        config_path = PROJECT_ROOT / "config" / "settings.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        load_and_merge(
            base_model_name=config["model"]["base_model"],
            adapter_path=str(PROJECT_ROOT / config["model"]["adapter_path"]),
            output_path=str(PROJECT_ROOT / config["model"]["merged_path"]),
        )

    if args.step in ("evaluate", "all"):
        logger.info("=== Step 3: Evaluating model ===")
        from src.training.evaluate import (
            calculate_perplexity,
            generate_samples,
            evaluate_persona_consistency,
            print_evaluation_report,
        )
        from src.persona.character import Persona
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        import torch
        import yaml

        config_path = PROJECT_ROOT / "config" / "settings.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)

        merged_path = str(PROJECT_ROOT / config["model"]["merged_path"])
        logger.info(f"Loading model from {merged_path}...")

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        tokenizer = AutoTokenizer.from_pretrained(merged_path)
        model = AutoModelForCausalLM.from_pretrained(
            merged_path,
            quantization_config=bnb_config,
            device_map="auto",
        )

        persona = Persona()

        # Evaluation prompts
        eval_prompts = [
            "오늘 카페에서 보낸 하루에 대한 인스타그램 캡션을 작성해줘",
            "봄 날씨가 좋은 날 산책하면서 찍은 사진 캡션",
            "새로운 맛집을 발견했을 때의 캡션",
            "주말 일상에 대한 캡션",
            "예쁜 옷을 입고 OOTD를 올릴 때의 캡션",
        ]

        samples = generate_samples(model, tokenizer, eval_prompts, num_samples=10)
        persona_scores = evaluate_persona_consistency(samples, persona)
        print_evaluation_report(0.0, persona_scores, samples)

    logger.info("=== Training pipeline complete ===")


if __name__ == "__main__":
    main()
