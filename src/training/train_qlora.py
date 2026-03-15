"""
QLoRA fine-tuning for the AI Influencer persona model.

Supports two backends:
  1. **Unsloth** (preferred) -- faster, memory-efficient patching.
  2. **PEFT + bitsandbytes** (fallback) -- standard HuggingFace stack.

Hardware target: NVIDIA RTX 3050 4 GB VRAM, CUDA 12.6.
"""

from __future__ import annotations

import gc
import os
import sys
from pathlib import Path
from typing import Any

import torch
import yaml
from datasets import Dataset, load_from_disk
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)
from trl import SFTConfig, SFTTrainer

from src.utils.logger import get_logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"

logger = get_logger()

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _load_config(path: Path = _CONFIG_PATH) -> dict[str, Any]:
    """Load project settings from YAML."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def load_dataset_from_processed(data_dir: Path) -> Dataset:
    """Load the pre-processed training dataset.

    Supports two on-disk formats:
      * Arrow (``datasets.load_from_disk``) - looks for final_dataset/ first
      * JSONL (``Dataset.from_json``)
    """
    processed_dir = data_dir / "processed"

    # Check for final_dataset (DatasetDict with train/validation splits)
    final_ds_path = processed_dir / "final_dataset"
    if final_ds_path.exists() and (final_ds_path / "train").exists():
        logger.info("Loading Arrow DatasetDict from {}", final_ds_path)
        ds_dict = load_from_disk(str(final_ds_path))
        # Return train split for training
        return ds_dict["train"]

    # Check for Arrow dataset directly in processed/
    if (processed_dir / "dataset_info.json").exists():
        logger.info("Loading Arrow dataset from {}", processed_dir)
        return load_from_disk(str(processed_dir))

    # Check subdirs for Arrow datasets
    for sub in sorted(processed_dir.iterdir()):
        if sub.is_dir() and (sub / "dataset_info.json").exists():
            logger.info("Loading Arrow dataset from {}", sub)
            return load_from_disk(str(sub))

    # JSONL fallback
    jsonl_candidates = list(processed_dir.glob("*.jsonl"))
    if jsonl_candidates:
        jsonl_path = jsonl_candidates[0]
        logger.info("Loading JSONL dataset from {}", jsonl_path)
        return Dataset.from_json(str(jsonl_path))

    raise FileNotFoundError(
        f"No dataset found in {processed_dir}. "
        "Run the data pipeline first (scripts/collect_data.py)."
    )


# ---------------------------------------------------------------------------
# Unsloth backend
# ---------------------------------------------------------------------------


def _train_with_unsloth(
    cfg: dict[str, Any],
    dataset: Dataset,
    max_seq_length: int,
    output_dir: str,
) -> None:
    """Fine-tune using the Unsloth fast-patching library."""
    from unsloth import FastLanguageModel

    base_model_name: str = cfg["model"]["base_model"]
    fallback_model_name: str = cfg["model"]["fallback_model"]

    logger.info("Unsloth backend: loading model '{}'", base_model_name)

    try:
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model_name,
            max_length=max_seq_length,
            dtype=torch.bfloat16,
            load_in_4bit=True,
        )
    except Exception as exc:
        logger.warning(
            "Failed to load '{}': {}. Falling back to '{}'",
            base_model_name,
            exc,
            fallback_model_name,
        )
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=fallback_model_name,
            max_length=max_seq_length,
            dtype=torch.bfloat16,
            load_in_4bit=True,
        )

    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
        max_length=max_seq_length,
    )

    training_args = _build_training_args(output_dir, max_seq_length)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        max_length=max_seq_length,
    )

    logger.info("Starting Unsloth QLoRA training (seq_len={})", max_seq_length)
    trainer.train()

    # Save LoRA adapter only
    adapter_path = str(_PROJECT_ROOT / cfg["model"]["adapter_path"])
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info("Adapter saved to {}", adapter_path)


# ---------------------------------------------------------------------------
# PEFT + bitsandbytes fallback backend
# ---------------------------------------------------------------------------


def _train_with_peft(
    cfg: dict[str, Any],
    dataset: Dataset,
    max_seq_length: int,
    output_dir: str,
) -> None:
    """Fine-tune using standard PEFT + bitsandbytes (no Unsloth)."""
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

    base_model_name: str = cfg["model"]["base_model"]
    fallback_model_name: str = cfg["model"]["fallback_model"]

    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    logger.info("PEFT backend: loading model '{}'", base_model_name)

    model = AutoModelForCausalLM.from_pretrained(
        base_model_name,
        quantization_config=quant_config,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    sft_config = _build_sft_config(output_dir, max_seq_length)

    # Prepare dataset: add 'text' column with formatted instruction-output pairs
    def format_example(example):
        return {"text": f"### Instruction:\n{example['instruction']}\n\n### Response:\n{example['output']}"}

    formatted_dataset = dataset.map(format_example)

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=formatted_dataset,
        args=sft_config,
    )

    logger.info("Starting PEFT QLoRA training (seq_len={})", max_seq_length)
    trainer.train()

    adapter_path = str(_PROJECT_ROOT / cfg["model"]["adapter_path"])
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info("Adapter saved to {}", adapter_path)


# ---------------------------------------------------------------------------
# Training arguments
# ---------------------------------------------------------------------------


def _build_sft_config(output_dir: str, max_seq_length: int) -> SFTConfig:
    """Construct ``SFTConfig`` tuned for RTX 3050 4 GB."""
    use_wandb = os.getenv("WANDB_ENABLED", "false").lower() in ("1", "true", "yes")

    return SFTConfig(
        output_dir=output_dir,
        max_length=max_seq_length,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_steps=1,
        num_train_epochs=3,
        bf16=True,
        logging_steps=1,
        save_strategy="no",
        save_total_limit=1,
        gradient_checkpointing=True,
        optim="adamw_8bit",
        report_to="wandb" if use_wandb else "none",
        max_grad_norm=0.3,
        weight_decay=0.01,
        dataloader_pin_memory=False,
        dataset_text_field="text",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def train(
    config_path: Path = _CONFIG_PATH,
    num_epochs: int | None = None,
    resume_from: str | None = None,
) -> None:
    """Run QLoRA fine-tuning with automatic OOM fallback.

    Strategy:
      1. Try Unsloth with ``max_seq_length`` from config (default 512).
      2. If Unsloth import fails, fall back to PEFT + bitsandbytes.
      3. If CUDA OOM occurs, retry with ``max_seq_length=256``.
    """
    cfg = _load_config(config_path)
    data_dir = _PROJECT_ROOT / cfg["paths"]["data_dir"]
    max_seq_length: int = cfg["model"].get("max_seq_length", 512)
    output_dir = str(_PROJECT_ROOT / "outputs" / "training")

    dataset = load_dataset_from_processed(data_dir)
    logger.info("Dataset loaded: {} examples", len(dataset))

    if num_epochs is not None:
        # Will be applied in _build_training_args override below
        pass

    # Determine backend
    try:
        import unsloth  # noqa: F401

        backend = "unsloth"
        train_fn = _train_with_unsloth
        logger.info("Unsloth detected -- using Unsloth backend")
    except ImportError:
        backend = "peft"
        train_fn = _train_with_peft
        logger.info("Unsloth not available -- using PEFT + bitsandbytes backend")

    # Try progressively smaller configs on OOM
    fallback_configs = [
        {"seq_len": max_seq_length, "model_override": None},
        {"seq_len": max_seq_length, "model_override": cfg["model"]["fallback_model"]},
        {"seq_len": 256, "model_override": cfg["model"]["fallback_model"]},
    ]

    for i, fb in enumerate(fallback_configs):
        try:
            if fb["model_override"]:
                cfg_copy = {**cfg, "model": {**cfg["model"], "base_model": fb["model_override"]}}
            else:
                cfg_copy = cfg

            # Aggressively clear GPU memory before each attempt
            gc.collect()
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()

            train_fn(cfg_copy, dataset, fb["seq_len"], output_dir)
            logger.success(
                "Training completed (backend={}, model={}, seq_len={})",
                backend,
                cfg_copy["model"]["base_model"],
                fb["seq_len"],
            )
            return
        except (torch.cuda.OutOfMemoryError, ValueError, RuntimeError) as exc:
            # Ensure all tensors are freed
            gc.collect()
            torch.cuda.empty_cache()
            if i < len(fallback_configs) - 1:
                next_fb = fallback_configs[i + 1]
                logger.warning(
                    "OOM/Error: {}. Retrying with model={}, seq_len={} ...",
                    str(exc)[:100],
                    next_fb.get("model_override") or cfg["model"]["base_model"],
                    next_fb["seq_len"],
                )
            else:
                logger.error("All fallback configs exhausted. Cannot train on this GPU.")
                raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    config_file = Path(sys.argv[1]) if len(sys.argv) > 1 else _CONFIG_PATH
    train(config_path=config_file)
