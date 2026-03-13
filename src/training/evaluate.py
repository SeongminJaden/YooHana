"""
Model evaluation utilities for the AI Influencer project.

Provides:
  - Perplexity calculation on an evaluation dataset
  - Sample text generation from a list of prompts
  - Persona-consistency scoring of generated samples
  - A formatted evaluation report printed to the console
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Any

import torch
import yaml
from datasets import Dataset
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedModel,
    PreTrainedTokenizerBase,
)

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
# Perplexity
# ---------------------------------------------------------------------------


def calculate_perplexity(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    eval_dataset: Dataset,
    max_length: int = 512,
    batch_size: int = 1,
) -> float:
    """Calculate perplexity of *model* over *eval_dataset*.

    Parameters
    ----------
    model:
        A causal-LM (possibly quantised / merged).
    tokenizer:
        The corresponding tokenizer.
    eval_dataset:
        A ``datasets.Dataset`` whose ``"text"`` column will be evaluated.
    max_length:
        Maximum token length for each sample.
    batch_size:
        Evaluation batch size (keep at 1 for low-VRAM GPUs).

    Returns
    -------
    float
        The corpus-level perplexity (lower is better).
    """
    model.eval()
    device = next(model.parameters()).device

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Determine the text column
    text_column = "text"
    if text_column not in eval_dataset.column_names:
        # Fall back to the first string-like column
        for col in eval_dataset.column_names:
            if isinstance(eval_dataset[0][col], str):
                text_column = col
                break

    texts: list[str] = eval_dataset[text_column]

    total_loss: float = 0.0
    total_tokens: int = 0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i : i + batch_size]
        encodings = tokenizer(
            batch_texts,
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
            padding=True,
        ).to(device)

        with torch.no_grad():
            outputs = model(**encodings, labels=encodings["input_ids"])

        # outputs.loss is the mean token-level cross-entropy for the batch
        num_tokens = encodings["attention_mask"].sum().item()
        total_loss += outputs.loss.item() * num_tokens
        total_tokens += num_tokens

    avg_loss = total_loss / total_tokens if total_tokens > 0 else float("inf")
    perplexity = math.exp(avg_loss)
    return perplexity


# ---------------------------------------------------------------------------
# Sample generation
# ---------------------------------------------------------------------------


def generate_samples(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    prompts: list[str],
    num_samples: int = 10,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.9,
    top_k: int = 50,
    repetition_penalty: float = 1.15,
) -> list[str]:
    """Generate text completions for a list of prompts.

    If *prompts* has fewer entries than *num_samples*, prompts are cycled;
    if it has more, only the first *num_samples* are used.

    Parameters
    ----------
    model:
        A causal-LM.
    tokenizer:
        The corresponding tokenizer.
    prompts:
        Seed prompts for generation.
    num_samples:
        Total number of samples to produce.
    max_new_tokens:
        Maximum new tokens per sample.
    temperature, top_p, top_k, repetition_penalty:
        Decoding hyper-parameters.

    Returns
    -------
    list[str]
        Generated text strings (prompt + completion).
    """
    model.eval()
    device = next(model.parameters()).device

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Cycle prompts if fewer than num_samples
    effective_prompts = [prompts[i % len(prompts)] for i in range(num_samples)]

    samples: list[str] = []
    for prompt in effective_prompts:
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repetition_penalty=repetition_penalty,
                do_sample=True,
                pad_token_id=tokenizer.pad_token_id,
            )
        generated_text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        samples.append(generated_text)

    return samples


# ---------------------------------------------------------------------------
# Persona consistency
# ---------------------------------------------------------------------------


def evaluate_persona_consistency(
    samples: list[str],
    persona: dict[str, Any],
) -> dict[str, Any]:
    """Score how well generated *samples* adhere to the target *persona*.

    The ``persona`` dict should contain at least some of the following keys
    (all optional -- metrics are computed only for keys that are present):

    - ``name`` (str): expected character name
    - ``keywords`` (list[str]): vocabulary the persona should use
    - ``prohibited_words`` (list[str]): words the persona must avoid
    - ``tone`` (str): e.g. "friendly", "formal" -- used for heuristic
    - ``language`` (str): expected primary language, e.g. "ko" for Korean

    Returns
    -------
    dict[str, Any]
        A dictionary with the following structure::

            {
                "total_samples": int,
                "keyword_hit_rate": float,      # 0.0 - 1.0
                "prohibited_word_rate": float,   # 0.0 - 1.0 (lower is better)
                "avg_response_length": float,    # in characters
                "language_consistency": float,   # 0.0 - 1.0
                "scores_per_sample": list[dict],
            }
    """
    if not samples:
        return {
            "total_samples": 0,
            "keyword_hit_rate": 0.0,
            "prohibited_word_rate": 0.0,
            "avg_response_length": 0.0,
            "language_consistency": 0.0,
            "scores_per_sample": [],
        }

    keywords: list[str] = persona.get("keywords", [])
    prohibited: list[str] = persona.get("prohibited_words", [])
    expected_lang: str = persona.get("language", "")

    total_keyword_hits = 0
    total_prohibited_hits = 0
    total_length = 0
    language_match_count = 0
    per_sample: list[dict[str, Any]] = []

    for idx, sample in enumerate(samples):
        sample_lower = sample.lower()
        sample_len = len(sample)
        total_length += sample_len

        # Keyword hits
        kw_hits = sum(1 for kw in keywords if kw.lower() in sample_lower)
        kw_rate = kw_hits / len(keywords) if keywords else 1.0
        total_keyword_hits += kw_hits

        # Prohibited word hits
        pw_hits = sum(1 for pw in prohibited if pw.lower() in sample_lower)
        pw_rate = pw_hits / len(prohibited) if prohibited else 0.0
        total_prohibited_hits += pw_hits

        # Language consistency heuristic
        lang_ok = _check_language(sample, expected_lang) if expected_lang else True
        if lang_ok:
            language_match_count += 1

        per_sample.append(
            {
                "index": idx,
                "length": sample_len,
                "keyword_hit_rate": round(kw_rate, 4),
                "prohibited_word_count": pw_hits,
                "language_match": lang_ok,
            }
        )

    n = len(samples)
    max_kw_hits = len(keywords) * n if keywords else 1
    max_pw_hits = len(prohibited) * n if prohibited else 1

    return {
        "total_samples": n,
        "keyword_hit_rate": round(total_keyword_hits / max_kw_hits, 4),
        "prohibited_word_rate": round(total_prohibited_hits / max_pw_hits, 4),
        "avg_response_length": round(total_length / n, 2),
        "language_consistency": round(language_match_count / n, 4),
        "scores_per_sample": per_sample,
    }


def _check_language(text: str, lang_code: str) -> bool:
    """Heuristic check whether *text* is predominantly in *lang_code*.

    Currently supports ``"ko"`` (Korean) and ``"en"`` (English).
    Returns ``True`` for unsupported language codes (optimistic default).
    """
    if lang_code == "ko":
        # Korean Hangul syllables: U+AC00 -- U+D7A3
        korean_chars = len(re.findall(r"[\uac00-\ud7a3]", text))
        alpha_chars = len(re.findall(r"[a-zA-Z\uac00-\ud7a3]", text))
        if alpha_chars == 0:
            return True
        return (korean_chars / alpha_chars) > 0.5

    if lang_code == "en":
        ascii_alpha = len(re.findall(r"[a-zA-Z]", text))
        total_alpha = len(re.findall(r"\w", text))
        if total_alpha == 0:
            return True
        return (ascii_alpha / total_alpha) > 0.7

    # Unknown language code -- assume match
    return True


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def print_evaluation_report(
    perplexity: float,
    persona_scores: dict[str, Any],
    samples: list[str],
    max_display_samples: int = 5,
) -> None:
    """Print a formatted evaluation report to stdout.

    Parameters
    ----------
    perplexity:
        Model perplexity on the evaluation set.
    persona_scores:
        Output of :func:`evaluate_persona_consistency`.
    samples:
        Generated sample texts.
    max_display_samples:
        Number of sample texts to display in the report.
    """
    separator = "=" * 72

    print(f"\n{separator}")
    print("  AI Influencer -- Model Evaluation Report")
    print(separator)

    # -- Perplexity --------------------------------------------------------
    print(f"\n  Perplexity : {perplexity:.4f}")

    # -- Persona consistency -----------------------------------------------
    print(f"\n  Persona Consistency")
    print(f"  {'Metric':<30s} {'Value':>10s}")
    print(f"  {'-' * 30} {'-' * 10}")
    print(
        f"  {'Total samples':<30s} {persona_scores['total_samples']:>10d}"
    )
    print(
        f"  {'Keyword hit rate':<30s} {persona_scores['keyword_hit_rate']:>10.2%}"
    )
    print(
        f"  {'Prohibited word rate':<30s} {persona_scores['prohibited_word_rate']:>10.2%}"
    )
    print(
        f"  {'Avg response length (chars)':<30s} {persona_scores['avg_response_length']:>10.1f}"
    )
    print(
        f"  {'Language consistency':<30s} {persona_scores['language_consistency']:>10.2%}"
    )

    # -- Generated samples -------------------------------------------------
    display_count = min(max_display_samples, len(samples))
    if display_count > 0:
        print(f"\n  Generated Samples (showing {display_count}/{len(samples)})")
        print(f"  {'-' * 68}")
        for i in range(display_count):
            # Truncate long samples for readability
            preview = samples[i][:300]
            if len(samples[i]) > 300:
                preview += " ..."
            print(f"\n  [{i + 1}] {preview}")

    print(f"\n{separator}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point that loads the merged model and runs evaluation."""
    import argparse

    from datasets import load_from_disk

    cfg = _load_config()

    parser = argparse.ArgumentParser(description="Evaluate the AI Influencer model.")
    parser.add_argument(
        "--model",
        type=str,
        default=str(_PROJECT_ROOT / cfg["model"]["merged_path"]),
        help="Path to the merged model (or HF model ID)",
    )
    parser.add_argument(
        "--eval-data",
        type=str,
        default=str(_PROJECT_ROOT / "data" / "processed"),
        help="Path to the evaluation dataset (Arrow format)",
    )
    parser.add_argument(
        "--prompts",
        type=str,
        nargs="+",
        default=None,
        help="Prompts for sample generation",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=10,
        help="Number of samples to generate",
    )
    args = parser.parse_args()

    # -- Load model & tokenizer -------------------------------------------
    logger.info("Loading model from '{}' ...", args.model)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # -- Perplexity -------------------------------------------------------
    logger.info("Calculating perplexity ...")
    eval_dataset = load_from_disk(args.eval_data)
    ppl = calculate_perplexity(model, tokenizer, eval_dataset)
    logger.info("Perplexity: {:.4f}", ppl)

    # -- Sample generation ------------------------------------------------
    default_prompts = [
        "What do you enjoy doing on weekends?",
        "How would you describe your personal style?",
        "Tell me about your favorite travel destination.",
        "What kind of music are you into?",
        "Share your morning routine.",
    ]
    prompts = args.prompts if args.prompts else default_prompts
    logger.info("Generating {} samples ...", args.num_samples)
    samples = generate_samples(
        model,
        tokenizer,
        prompts,
        num_samples=args.num_samples,
        max_new_tokens=cfg["generation"]["max_new_tokens"],
        temperature=cfg["generation"]["temperature"],
        top_p=cfg["generation"]["top_p"],
        top_k=cfg["generation"]["top_k"],
        repetition_penalty=cfg["generation"]["repetition_penalty"],
    )

    # -- Persona consistency (minimal persona for CLI) --------------------
    persona: dict[str, Any] = {
        "keywords": [],
        "prohibited_words": [],
        "language": "ko",
    }
    persona_scores = evaluate_persona_consistency(samples, persona)

    # -- Report -----------------------------------------------------------
    print_evaluation_report(ppl, persona_scores, samples)


if __name__ == "__main__":
    main()
