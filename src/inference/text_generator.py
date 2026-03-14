"""Fine-tuned model text generation for the AI Influencer project.

Loads a 4-bit quantized base model + LoRA adapter via ``transformers`` +
``bitsandbytes`` + ``peft`` and exposes convenient methods for caption /
reply generation.  Expected VRAM usage: ~1.6 GB.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Optional

import torch
import yaml
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from src.inference.memory import PostMemory
from src.inference.prompt_builder import PromptBuilder
from src.persona.character import Persona
from src.utils.logger import get_logger

logger = get_logger()

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _load_settings() -> dict:
    """Load ``config/settings.yaml`` and return its contents as a dict."""
    settings_path = _CONFIG_DIR / "settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class TextGenerator:
    """Singleton text generator backed by a 4-bit quantized causal LM + LoRA.

    Loads the base model (Qwen2.5-1.5B-Instruct) in 4-bit and applies
    the fine-tuned LoRA adapter on top.  Falls back to the adapter path
    if a merged model directory is not available.

    The class implements the singleton pattern so that the (expensive)
    model is loaded at most once per process.
    """

    _instance: Optional["TextGenerator"] = None
    _lock: threading.Lock = threading.Lock()
    _initialised: bool = False

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    def __new__(cls, model_path: Optional[str] = None) -> "TextGenerator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, model_path: Optional[str] = None) -> None:
        if self._initialised:
            return

        self._settings = _load_settings()
        self._project_root = Path(__file__).resolve().parents[2]

        # Quantisation config -----------------------------------------------
        quant_cfg = self._settings["model"]["quantization"]
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=quant_cfg["load_in_4bit"],
            bnb_4bit_quant_type=quant_cfg["bnb_4bit_quant_type"],
            bnb_4bit_use_double_quant=quant_cfg["bnb_4bit_use_double_quant"],
            bnb_4bit_compute_dtype=getattr(
                torch, quant_cfg["bnb_4bit_compute_dtype"]
            ),
        )

        # Resolve paths ------------------------------------------------------
        merged_path = self._project_root / self._settings["model"]["merged_path"]
        adapter_path = self._project_root / self._settings["model"]["adapter_path"]

        if merged_path.exists() and (merged_path / "config.json").exists():
            # Merged model available: load directly
            logger.info("Loading merged model from {} ...", merged_path)
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(merged_path), trust_remote_code=True,
            )
            self._model = AutoModelForCausalLM.from_pretrained(
                str(merged_path),
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
            )
        elif adapter_path.exists() and (adapter_path / "adapter_config.json").exists():
            # Load base model + apply LoRA adapter
            base_model_name = self._settings["model"]["fallback_model"]  # Qwen2.5-1.5B
            logger.info("Loading base model '{}' + adapter from {} ...",
                        base_model_name, adapter_path)
            self._tokenizer = AutoTokenizer.from_pretrained(
                base_model_name, trust_remote_code=True,
            )
            base_model = AutoModelForCausalLM.from_pretrained(
                base_model_name,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
            )
            self._model = PeftModel.from_pretrained(base_model, str(adapter_path))
            logger.info("LoRA adapter applied.")
        else:
            raise FileNotFoundError(
                f"Neither merged model ({merged_path}) nor adapter ({adapter_path}) found."
            )

        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model.eval()
        logger.success("Model loaded successfully.")

        # Generation defaults -------------------------------------------------
        gen_cfg = self._settings["generation"]
        self._default_temperature: float = gen_cfg["temperature"]
        self._default_top_p: float = gen_cfg["top_p"]
        self._default_top_k: int = gen_cfg["top_k"]
        self._default_repetition_penalty: float = gen_cfg["repetition_penalty"]
        self._default_max_new_tokens: int = gen_cfg["max_new_tokens"]

        # Persona & prompt builder -------------------------------------------
        self._persona = Persona()
        self._prompt_builder = PromptBuilder(self._persona)
        self._memory = PostMemory()

        self._initialised = True

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
    ) -> str:
        """Generate text from a raw string prompt.

        Parameters
        ----------
        prompt:
            The fully formatted prompt string (e.g. already rendered via
            ``tokenizer.apply_chat_template``).
        max_new_tokens:
            Maximum number of tokens to generate.

        Returns
        -------
        str
            The model's generated text with the input prompt stripped.
        """
        inputs = self._tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self._settings["model"]["max_seq_length"],
        ).to(self._model.device)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=self._default_temperature,
                top_p=self._default_top_p,
                top_k=self._default_top_k,
                repetition_penalty=self._default_repetition_penalty,
                do_sample=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )

        # Decode only the newly generated tokens
        generated_ids = outputs[0][inputs["input_ids"].shape[-1] :]
        text = self._tokenizer.decode(
            generated_ids,
            skip_special_tokens=True,
        ).strip()
        return self._clean_output(text)

    # Common English terms allowed in Korean Instagram captions
    _ALLOWED_EN = {
        "OOTD", "ootd", "GRWM", "grwm", "daily", "cafe", "coffee",
        "style", "look", "selfie", "vlog", "photo", "mood", "food",
        "outfit", "brunch", "Seoul", "Kpop", "ENFP", "MBTI",
        "DM", "SNS", "IT", "OK", "ok", "lol", "OMG",
    }

    @classmethod
    def _clean_output(cls, text: str) -> str:
        """Clean up model output: remove non-Korean script leakage."""
        # Remove Chinese characters (CJK Unified Ideographs)
        text = re.sub(r"[\u4e00-\u9fff]+", "", text)
        # Remove Japanese Hiragana/Katakana
        text = re.sub(r"[\u3040-\u309f\u30a0-\u30ff]+", "", text)
        # Remove Cyrillic characters
        text = re.sub(r"[\u0400-\u04ff]+", "", text)
        # Remove other non-Korean/non-ASCII stray characters
        text = re.sub(r"[\u2e80-\u2eff\u3000-\u303f\ufb50-\ufdff]+", "", text)
        # Remove invisible/formatting unicode
        text = re.sub(r"[\u200b-\u200f\u2028-\u202f\u2060-\u206f\ufe00-\ufe0f\u2063]+", "", text)
        # Remove stray English words (3+ chars) not in allowlist
        def _filter_en(m: re.Match) -> str:
            return m.group(0) if m.group(0) in cls._ALLOWED_EN else ""
        text = re.sub(r"\b[A-Za-z]{3,}\b", _filter_en, text)
        # Remove empty parentheses/brackets left after cleanup
        text = re.sub(r"\(\s*\)", "", text)
        text = re.sub(r"\[\s*\]", "", text)
        # Clean up resulting double spaces or orphaned punctuation
        text = re.sub(r"  +", " ", text)
        text = re.sub(r" ([.,!?~])", r"\1", text)
        return text.strip()

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def _render_prompt(self, messages: list[dict[str, str]]) -> str:
        """Render messages into the training-time format.

        The model was fine-tuned with ``### Instruction: ... ### Response: ...``
        format, so we use that for inference rather than chat templates.
        """
        # Combine system + user messages into a single instruction block
        parts: list[str] = []
        for msg in messages:
            parts.append(msg["content"])
        instruction = "\n\n".join(parts)

        return f"### Instruction:\n{instruction}\n\n### Response:\n"

    @property
    def memory(self) -> PostMemory:
        """Access the post/comment memory system."""
        return self._memory

    def generate_caption(self, topic: str, context: str = "") -> str:
        """Generate an Instagram caption with memory context.

        Includes recent post history to avoid repetition.
        """
        # Build memory context
        memory_ctx = self._memory.build_post_context(max_posts=5)
        if memory_ctx:
            instruction = (
                f"{memory_ctx}\n\n"
                f"위 게시글과 겹치지 않게, {topic}에 대한 인스타그램 캡션을 작성해줘"
            )
        else:
            instruction = f"{topic}에 대한 인스타그램 캡션을 작성해줘"

        prompt = f"### Instruction:\n{instruction}\n\n### Response:\n"
        logger.debug("Caption prompt length: {} chars", len(prompt))
        return self.generate(prompt, max_new_tokens=self._default_max_new_tokens)

    def generate_reply(self, comment: str, post_caption: str = "") -> str:
        """Generate a reply with memory of past interactions."""
        # Include post caption and recent reply context
        memory_ctx = self._memory.build_comment_context(max_comments=5)

        parts = []
        if post_caption:
            parts.append(f"[내 게시글] {post_caption}")
        if memory_ctx:
            parts.append(memory_ctx)
        parts.append(f"[팔로워 댓글] {comment}")
        parts.append("이 댓글에 답글을 써줘")

        instruction = "\n".join(parts)
        prompt = f"### Instruction:\n{instruction}\n\n### Response:\n"
        logger.debug("Reply prompt length: {} chars", len(prompt))
        return self.generate(prompt, max_new_tokens=128)

    def generate_plan(
        self,
        recent_posts: list[str],
        season: str,
    ) -> str:
        """Generate a weekly content plan.

        Parameters
        ----------
        recent_posts:
            List of recent post captions / summaries.
        season:
            Current season (``"spring"``, ``"summer"``, ``"autumn"``,
            ``"winter"``).

        Returns
        -------
        str
            The generated weekly plan text.
        """
        messages = self._prompt_builder.build_planning_prompt(
            recent_posts=recent_posts,
            season=season,
        )
        prompt = self._render_prompt(messages)
        logger.debug("Planning prompt length: {} chars", len(prompt))
        # Plans can be longer
        return self.generate(prompt, max_new_tokens=512)
