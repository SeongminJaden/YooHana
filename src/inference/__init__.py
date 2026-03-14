"""Inference module — text generation with fine-tuned model."""

__all__ = ["TextGenerator", "PromptBuilder", "PostMemory"]


def __getattr__(name):
    """Lazy import to avoid loading the model at module import time."""
    if name == "TextGenerator":
        from src.inference.text_generator import TextGenerator
        return TextGenerator
    if name == "PromptBuilder":
        from src.inference.prompt_builder import PromptBuilder
        return PromptBuilder
    if name == "PostMemory":
        from src.inference.memory import PostMemory
        return PostMemory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
