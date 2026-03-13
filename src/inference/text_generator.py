"""Fine-tuned model text generation for the AI Influencer project.

Loads a 4-bit quantized model via ``transformers`` + ``bitsandbytes`` and
exposes convenient methods for caption / reply generation.
Expected VRAM usage: ~1.6 GB.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

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
    """Singleton text generator backed by a 4-bit quantized causal LM.

    Parameters
    ----------
    model_path:
        Path to the merged (or adapter-merged) model directory.  When
        *None*, the path is resolved from ``config/settings.yaml``
        (``model.merged_path``).

    Notes
    -----
    The class implements the singleton pattern so that the (expensive)
    model is loaded at most once per process.  Use ``TextGenerator()``
    freely – repeated calls return the same instance.
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
        # Guard against re-initialisation on repeated __init__ calls.
        if self._initialised:
            return

        self._settings = _load_settings()
        self._project_root = Path(__file__).resolve().parents[2]

        # Resolve model path ------------------------------------------------
        if model_path is None:
            model_path = str(
                self._project_root / self._settings["model"]["merged_path"]
            )
        self._model_path = Path(model_path)
        logger.info("Model path resolved to: {}", self._model_path)

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

        # Load tokenizer & model ---------------------------------------------
        logger.info("Loading tokenizer from {} ...", self._model_path)
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(self._model_path),
            trust_remote_code=True,
        )

        logger.info("Loading 4-bit quantized model (~1.6 GB VRAM) ...")
        self._model = AutoModelForCausalLM.from_pretrained(
            str(self._model_path),
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
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
        return self._tokenizer.decode(
            generated_ids,
            skip_special_tokens=True,
        ).strip()

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def _render_prompt(self, messages: list[dict[str, str]]) -> str:
        """Apply the tokenizer chat template to a list of message dicts.

        Falls back to a simple concatenation when the tokenizer has no
        chat template configured.
        """
        try:
            return self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception:
            # Fallback: plain concatenation for models without a template.
            parts: list[str] = []
            for msg in messages:
                role = msg["role"]
                content = msg["content"]
                if role == "system":
                    parts.append(f"[System]\n{content}\n")
                elif role == "user":
                    parts.append(f"[User]\n{content}\n")
                elif role == "assistant":
                    parts.append(f"[Assistant]\n{content}\n")
            parts.append("[Assistant]\n")
            return "\n".join(parts)

    def generate_caption(self, topic: str, context: str = "") -> str:
        """Generate an Instagram caption for the given topic.

        Parameters
        ----------
        topic:
            The caption theme or topic (e.g. "카페 탐방").
        context:
            Optional recent-post context to help avoid repetition.

        Returns
        -------
        str
            The generated caption text.
        """
        messages = self._prompt_builder.build_caption_prompt(
            topic=topic,
            context=context,
        )
        prompt = self._render_prompt(messages)
        logger.debug("Caption prompt length: {} chars", len(prompt))
        return self.generate(prompt, max_new_tokens=self._default_max_new_tokens)

    def generate_reply(self, comment: str, post_caption: str = "") -> str:
        """Generate a reply to a follower comment.

        Parameters
        ----------
        comment:
            The follower comment to respond to.
        post_caption:
            Optional original post caption for context.

        Returns
        -------
        str
            The generated reply text.
        """
        messages = self._prompt_builder.build_reply_prompt(
            comment=comment,
            post_caption=post_caption,
        )
        prompt = self._render_prompt(messages)
        logger.debug("Reply prompt length: {} chars", len(prompt))
        # Replies are short; cap at 128 tokens.
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
