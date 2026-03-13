"""
Gemini API wrapper for AI Influencer image generation.

Uses the google-genai client to generate photorealistic images via
Gemini models, with support for reference images (character consistency)
and automatic retry on transient errors.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "images"


class ContentFilterError(Exception):
    """Raised when the Gemini API rejects a prompt due to content filtering."""


class GeminiImageClient:
    """Wrapper around the Google GenAI client for image generation.

    Parameters
    ----------
    api_key : str | None
        Gemini API key.  Falls back to the ``GEMINI_API_KEY`` environment
        variable when not provided.
    model : str
        Gemini model identifier to use for image generation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash-exp",
    ) -> None:
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Gemini API key is required. Set GEMINI_API_KEY env var or "
                "pass api_key explicitly."
            )

        self._client = genai.Client(api_key=resolved_key)
        self._model = model
        logger.info("GeminiImageClient initialised (model={})", self._model)

    # ------------------------------------------------------------------
    # Image generation
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def generate_image(
        self,
        prompt: str,
        reference_images: Optional[list[str]] = None,
    ) -> bytes:
        """Generate an image from a text prompt via Gemini.

        Parameters
        ----------
        prompt : str
            The text prompt describing the desired image.
        reference_images : list[str] | None
            Optional list of file paths to reference images.  When provided
            the images are included in the request to improve character
            consistency across generated images.

        Returns
        -------
        bytes
            Raw image data (PNG).

        Raises
        ------
        ContentFilterError
            If the request is blocked by the content safety filter.
        ConnectionError
            On transient network errors (retried automatically).
        RuntimeError
            When the API returns no image data.
        """
        logger.debug("Generating image – prompt length: {}", len(prompt))

        # Build request parts: optional reference images + text prompt.
        parts: list[types.Part] = []

        if reference_images:
            for ref_path in reference_images:
                ref = Path(ref_path)
                if not ref.exists():
                    logger.warning("Reference image not found, skipping: {}", ref)
                    continue
                image_bytes = ref.read_bytes()
                # Determine mime type from suffix
                suffix = ref.suffix.lower()
                mime_map = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }
                mime_type = mime_map.get(suffix, "image/png")
                parts.append(
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                )
            logger.debug(
                "Included {} reference image(s)", len(parts)
            )

        parts.append(types.Part.from_text(text=prompt))

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=parts,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "blocked" in exc_str or "safety" in exc_str or "filter" in exc_str:
                logger.error("Content filter triggered: {}", exc)
                raise ContentFilterError(
                    f"Image generation blocked by content filter: {exc}"
                ) from exc
            # Let tenacity handle transient errors
            raise

        # Check for content filter in response
        if not response.candidates:
            raise ContentFilterError(
                "No candidates returned – the prompt was likely filtered."
            )

        # Extract image bytes from the response
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                logger.info("Image generated successfully ({} bytes)", len(part.inline_data.data))
                return part.inline_data.data

        raise RuntimeError(
            "Gemini response contained no image data. "
            "Verify that the model supports image generation."
        )

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_image(
        self,
        image_data: bytes,
        filename: str,
        output_dir: str = "outputs/images",
    ) -> str:
        """Persist raw image data to disk.

        Parameters
        ----------
        image_data : bytes
            Raw image bytes (typically PNG).
        filename : str
            Target filename, e.g. ``"feed_20260313_001.png"``.
        output_dir : str
            Directory for saved images.  Relative paths are resolved from
            the project root.

        Returns
        -------
        str
            Absolute path to the saved file.
        """
        out_path = Path(output_dir)
        if not out_path.is_absolute():
            out_path = _PROJECT_ROOT / out_path

        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / filename
        file_path.write_bytes(image_data)

        logger.info("Image saved -> {}", file_path)
        return str(file_path)
