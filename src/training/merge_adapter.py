"""
Merge a LoRA adapter back into its base model and save the result.

Typical usage:
    python -m src.training.merge_adapter \\
        --base kakaocorp/kanana-nano-2.1b-instruct \\
        --adapter models/adapter \\
        --output models/merged
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch
import yaml
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from src.utils.logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"

logger = get_logger()


def _load_config(path: Path = _CONFIG_PATH) -> dict[str, Any]:
    """Load project settings from YAML."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------


def load_and_merge(
    base_model_name: str,
    adapter_path: str,
    output_path: str,
) -> None:
    """Load a 4-bit base model, apply a LoRA adapter, merge, and save.

    Parameters
    ----------
    base_model_name:
        HuggingFace model ID or local path for the base model.
    adapter_path:
        Path to the saved LoRA adapter directory (contains
        ``adapter_config.json`` and weight files).
    output_path:
        Destination directory for the fully-merged model and tokenizer.
    """
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # -- Quantization config (matches training) --------------------------------
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    # -- Load base model in 4-bit ----------------------------------------------
    logger.info("Loading base model '{}' in 4-bit ...", base_model_name)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=quant_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    # -- Load tokenizer ---------------------------------------------------------
    logger.info("Loading tokenizer from '{}'", base_model_name)
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # -- Attach adapter ---------------------------------------------------------
    logger.info("Loading LoRA adapter from '{}' ...", adapter_path)
    model = PeftModel.from_pretrained(base_model, adapter_path)

    # -- Merge and unload -------------------------------------------------------
    logger.info("Merging adapter weights into base model ...")
    model = model.merge_and_unload()

    # -- Save -------------------------------------------------------------------
    logger.info("Saving merged model to '{}' ...", output_path)
    model.save_pretrained(str(output_dir))

    logger.info("Saving tokenizer to '{}' ...", output_path)
    tokenizer.save_pretrained(str(output_dir))

    logger.success("Merge complete: {}", output_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point.

    Reads defaults from ``config/settings.yaml`` but allows overrides
    via ``--base``, ``--adapter``, and ``--output`` flags.
    """
    import argparse

    cfg = _load_config()

    parser = argparse.ArgumentParser(
        description="Merge a LoRA adapter into the base model.",
    )
    parser.add_argument(
        "--base",
        type=str,
        default=cfg["model"]["base_model"],
        help="Base model name or path (default: from settings.yaml)",
    )
    parser.add_argument(
        "--adapter",
        type=str,
        default=str(_PROJECT_ROOT / cfg["model"]["adapter_path"]),
        help="Path to the LoRA adapter directory",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(_PROJECT_ROOT / cfg["model"]["merged_path"]),
        help="Output directory for the merged model",
    )
    args = parser.parse_args()

    load_and_merge(
        base_model_name=args.base,
        adapter_path=args.adapter,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
