"""
Image analysis for NanoBanana prompt generation.

Analyzes crawled Instagram images to extract scene descriptions (people,
poses, clothing, expressions, backgrounds) and converts them into prompts
suitable for the NanoBanana / Gemini image generation API.

The goal: composite an illustration character (유하나) onto a real
background, making it look like the illustrated persona is actually
present in the scene.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from src.persona.character import Persona
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ──────────────────────────────────────────────────────────────────────
# Clothing style mapping (Korean → English for prompt)
# ──────────────────────────────────────────────────────────────────────

_CLOTHING_KEYWORDS: dict[str, str] = {
    "suit": "formal dark suit with blazer",
    "blazer": "smart casual blazer",
    "jacket": "stylish jacket",
    "coat": "long coat",
    "dress": "elegant dress",
    "casual": "casual outfit",
    "hoodie": "cozy hoodie",
    "sweater": "knit sweater",
    "t-shirt": "simple t-shirt",
    "jeans": "denim jeans",
    "skirt": "skirt",
    "athleisure": "sporty athleisure wear",
    "knitwear": "warm knitwear",
}

_POSE_KEYWORDS: dict[str, str] = {
    "selfie": "taking a selfie, looking at camera",
    "standing": "standing naturally",
    "sitting": "sitting comfortably",
    "walking": "walking casually",
    "posing": "posing for photo",
    "leaning": "leaning against a surface",
    "looking away": "looking into the distance",
}

_EXPRESSION_KEYWORDS: dict[str, str] = {
    "smiling": "warm smile",
    "laughing": "joyful laughter",
    "serious": "calm serious expression",
    "thoughtful": "thoughtful gaze",
    "surprised": "surprised expression",
    "neutral": "natural relaxed expression",
}


class ImageAnalyzer:
    """Analyze crawled images and extract scene information for prompt generation.

    Uses Instagram's alt-text descriptions and image metadata to build
    structured scene analyses without requiring a vision AI model.
    """

    def __init__(self, persona: Persona | None = None) -> None:
        self._persona = persona or Persona()
        self._data_dir = _PROJECT_ROOT / "data"

    def analyze_post(self, post: dict[str, Any]) -> dict[str, Any]:
        """Analyze a single crawled post and extract scene information.

        Parameters
        ----------
        post : dict
            A raw crawled post dict with keys like ``media_analysis``,
            ``instagram_descriptions``, ``caption``, ``image_urls``, etc.

        Returns
        -------
        dict
            Structured analysis with keys: ``scene``, ``clothing``,
            ``pose``, ``expression``, ``background``, ``mood``,
            ``lighting``, ``color_palette``, ``nanobana_prompt``.
        """
        analysis: dict[str, Any] = {
            "media_id": post.get("media_id", ""),
            "username": post.get("user", ""),
            "media_type": post.get("media_type", "photo"),
        }

        # Extract from Instagram alt-text descriptions
        media_analysis = post.get("media_analysis", {})
        ig_descriptions = media_analysis.get("instagram_descriptions", [])
        alt_text = " ".join(ig_descriptions).lower() if ig_descriptions else ""

        # Extract from caption
        caption = post.get("caption", "")

        # Analyze clothing
        analysis["clothing"] = self._detect_clothing(alt_text)

        # Analyze pose
        analysis["pose"] = self._detect_pose(alt_text)

        # Analyze expression
        analysis["expression"] = self._detect_expression(alt_text)

        # Analyze scene/background from alt text
        analysis["background"] = self._detect_background(alt_text, caption)

        # Image properties (from media_analysis)
        images = media_analysis.get("images", [])
        if images:
            img_info = images[0]
            analysis["lighting"] = self._infer_lighting(img_info)
            analysis["color_palette"] = {
                "brightness": img_info.get("brightness", 128),
                "tone": img_info.get("tone", "medium"),
                "temperature": img_info.get("temperature", "neutral"),
                "saturation": img_info.get("saturation", 0.5),
                "color_style": img_info.get("color_style", "natural"),
            }
            analysis["orientation"] = img_info.get("orientation", "portrait")
        else:
            analysis["lighting"] = "natural"
            analysis["color_palette"] = {}
            analysis["orientation"] = "portrait"

        # Generate mood from combined signals
        analysis["mood"] = self._infer_mood(analysis)

        # Generate NanoBanana composite prompt
        analysis["nanobana_prompt"] = self._build_composite_prompt(analysis)

        return analysis

    def analyze_all_posts(self) -> list[dict[str, Any]]:
        """Analyze all crawled posts in ``data/raw/``.

        Returns
        -------
        list[dict]
            List of analysis dicts for each post with images.
        """
        raw_dir = self._data_dir / "raw"
        results: list[dict[str, Any]] = []

        if not raw_dir.exists():
            logger.warning("No raw data directory found at {}", raw_dir)
            return results

        for json_file in sorted(raw_dir.glob("*.json")):
            try:
                posts = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(posts, list):
                    continue

                for post in posts:
                    # Skip posts without images
                    media_analysis = post.get("media_analysis", {})
                    if not media_analysis.get("images"):
                        continue

                    analysis = self.analyze_post(post)
                    results.append(analysis)

            except Exception as e:
                logger.warning("Failed to analyze {}: {}", json_file.name, e)

        logger.info("Analyzed {} posts with images", len(results))
        return results

    def save_analyses(
        self, analyses: list[dict[str, Any]], output_path: str | None = None,
    ) -> str:
        """Save analysis results to JSON.

        Parameters
        ----------
        analyses : list[dict]
            List of analysis results from :meth:`analyze_all_posts`.
        output_path : str | None
            Output file path. Defaults to ``data/processed/image_analyses.json``.

        Returns
        -------
        str
            Path to the saved file.
        """
        if output_path is None:
            out = self._data_dir / "processed" / "image_analyses.json"
        else:
            out = Path(output_path)

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(analyses, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved {} image analyses to {}", len(analyses), out)
        return str(out)

    # ──────────────────────────────────────────────────────────────────
    # Detection helpers
    # ──────────────────────────────────────────────────────────────────

    def _detect_clothing(self, alt_text: str) -> str:
        """Detect clothing from alt text."""
        for keyword, desc in _CLOTHING_KEYWORDS.items():
            if keyword in alt_text:
                return desc
        return "casual chic outfit"

    def _detect_pose(self, alt_text: str) -> str:
        """Detect pose from alt text."""
        for keyword, desc in _POSE_KEYWORDS.items():
            if keyword in alt_text:
                return desc

        if "selfie" in alt_text:
            return "taking a selfie, looking at camera"
        return "standing naturally, relaxed pose"

    def _detect_expression(self, alt_text: str) -> str:
        """Detect expression from alt text."""
        for keyword, desc in _EXPRESSION_KEYWORDS.items():
            if keyword in alt_text:
                return desc
        return "natural relaxed expression with a gentle smile"

    def _detect_background(self, alt_text: str, caption: str) -> str:
        """Detect background/scene from alt text and caption."""
        backgrounds: list[str] = []

        # Common background indicators in alt text
        bg_keywords = {
            "outdoor": "outdoor setting",
            "indoor": "indoor setting",
            "cafe": "cozy cafe interior",
            "restaurant": "restaurant interior",
            "street": "urban street",
            "park": "green park",
            "beach": "sandy beach with ocean",
            "mountain": "mountain scenery",
            "building": "modern building",
            "room": "cozy room interior",
            "sky": "open sky background",
            "tree": "trees and greenery",
            "flower": "flowers in the scene",
            "food": "food on table",
            "car": "near a car",
            "mirror": "mirror reflection",
        }

        combined = f"{alt_text} {caption.lower()}"
        for keyword, desc in bg_keywords.items():
            if keyword in combined:
                backgrounds.append(desc)

        if backgrounds:
            return ", ".join(backgrounds[:3])
        return "urban city setting, modern aesthetic"

    def _infer_lighting(self, img_info: dict) -> str:
        """Infer lighting conditions from image properties."""
        brightness = img_info.get("brightness", 128)
        temperature = img_info.get("temperature", "neutral")

        if brightness > 180:
            base = "bright"
        elif brightness > 130:
            base = "well-lit"
        elif brightness > 80:
            base = "moderate"
        else:
            base = "dim, moody"

        if temperature == "warm":
            return f"{base} warm-toned lighting"
        elif temperature == "cool":
            return f"{base} cool-toned lighting"
        return f"{base} natural lighting"

    def _infer_mood(self, analysis: dict) -> str:
        """Infer overall mood from combined signals."""
        palette = analysis.get("color_palette", {})
        brightness = palette.get("brightness", 128)
        saturation = palette.get("saturation", 0.5)

        if brightness > 160 and saturation > 0.3:
            return "bright and vibrant"
        elif brightness > 160:
            return "bright and airy"
        elif brightness > 100 and saturation > 0.3:
            return "warm and vivid"
        elif brightness > 100:
            return "calm and natural"
        elif saturation > 0.3:
            return "moody and rich"
        return "soft and subdued"

    # ──────────────────────────────────────────────────────────────────
    # NanoBanana prompt building
    # ──────────────────────────────────────────────────────────────────

    def _build_composite_prompt(self, analysis: dict) -> dict[str, str]:
        """Build a NanoBanana-compatible composite prompt.

        The concept: render the persona (유하나) as a 2D illustration
        character composited onto a real photograph background, so it
        looks like an anime/illustration character exists in the real
        scene.

        Returns
        -------
        dict
            Keys: ``character_prompt``, ``background_prompt``,
            ``composite_instruction``, ``style_guide``, ``full_prompt``.
        """
        persona = self._persona

        # Character prompt (illustration style)
        character_prompt = (
            f"A cute illustrated 2D anime-style character of a {persona.age}-year-old "
            f"Korean woman named {persona.name_en}. "
            f"Long wavy brown hair, large expressive brown eyes, "
            f"natural light makeup, slim build. "
            f"Expression: {analysis.get('expression', 'gentle smile')}. "
            f"Pose: {analysis.get('pose', 'standing naturally')}. "
            f"Wearing: {analysis.get('clothing', 'casual chic outfit')}. "
            f"Illustration style: clean line art with soft cel-shading, "
            f"pastel color palette, slight glow effect."
        )

        # Background prompt (photorealistic, from actual scene)
        background_prompt = (
            f"Photorealistic background photograph: {analysis.get('background', 'urban setting')}. "
            f"Lighting: {analysis.get('lighting', 'natural')}. "
            f"Mood: {analysis.get('mood', 'calm and natural')}. "
            f"High quality, sharp focus, natural colors."
        )

        # Composite instruction
        composite_instruction = (
            "Composite the illustrated 2D anime-style character seamlessly "
            "into the photorealistic background. The character should cast "
            "realistic shadows and have lighting that matches the background. "
            "The character's color palette should harmonize with the background "
            "colors. Maintain clear separation between the illustrated character "
            "and the photorealistic background for a distinctive mixed-media look."
        )

        # Style guide
        style_guide = (
            "Mixed-media art style: 2D illustrated anime character in a real photo. "
            "Character outline should be clean and visible. "
            "Character shading should reflect the background lighting direction. "
            "Instagram-worthy composition, 4:5 portrait orientation preferred. "
            f"Overall mood: {analysis.get('mood', 'bright and natural')}."
        )

        # Full combined prompt
        full_prompt = (
            f"{character_prompt}\n\n"
            f"Background: {background_prompt}\n\n"
            f"Composition: {composite_instruction}\n\n"
            f"Style: {style_guide}"
        )

        return {
            "character_prompt": character_prompt,
            "background_prompt": background_prompt,
            "composite_instruction": composite_instruction,
            "style_guide": style_guide,
            "full_prompt": full_prompt,
        }
