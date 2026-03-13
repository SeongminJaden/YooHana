"""Image generation module for the AI Influencer."""

from src.image_gen.image_processor import ImageProcessor
from src.image_gen.prompt_composer import ImagePromptComposer

__all__ = [
    "ImageProcessor",
    "ImagePromptComposer",
]


def __getattr__(name):
    """Lazy import for modules requiring google-genai."""
    if name == "GeminiImageClient":
        from src.image_gen.gemini_client import GeminiImageClient
        return GeminiImageClient
    if name == "ContentFilterError":
        from src.image_gen.gemini_client import ContentFilterError
        return ContentFilterError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
