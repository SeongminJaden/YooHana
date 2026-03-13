"""
Image prompt composition for the AI Influencer.

Builds detailed English prompts for Gemini image generation by combining
the persona's base appearance description with scene, mood, clothing,
and quality modifiers.
"""

from __future__ import annotations

from src.persona.character import Persona


# Quality keywords appended to every prompt
_QUALITY_SUFFIX = (
    "photorealistic, high quality, Instagram aesthetic, natural lighting"
)

# Negative prompt: things to avoid in generation
_NEGATIVE_PROMPT = (
    "deformed, blurry, low quality, watermark, text overlay, "
    "multiple people, extra limbs, disfigured, bad anatomy, "
    "out of frame, cropped, ugly, duplicate"
)


class ImagePromptComposer:
    """Compose image-generation prompts grounded in a :class:`Persona`.

    Parameters
    ----------
    persona : Persona
        A loaded :class:`~src.persona.character.Persona` instance whose
        ``appearance_prompt`` is used as the visual foundation for every
        generated prompt.
    """

    def __init__(self, persona: Persona) -> None:
        self._persona = persona
        self._base_prompt = persona.appearance_prompt

    # ------------------------------------------------------------------
    # Feed prompt
    # ------------------------------------------------------------------

    def compose_feed_prompt(
        self,
        scene: str,
        mood: str = "bright",
        clothing: str | None = None,
    ) -> str:
        """Build a prompt suitable for an Instagram feed image.

        Parameters
        ----------
        scene : str
            Description of the scene / setting,
            e.g. ``"sitting at an outdoor cafe table with a latte"``.
        mood : str
            Mood and lighting keyword, e.g. ``"bright"``, ``"golden hour"``,
            ``"moody"``, ``"soft pastel"``.
        clothing : str | None
            Optional clothing description override.  When *None* the
            persona's default style is used.

        Returns
        -------
        str
            A complete prompt ready for :meth:`GeminiImageClient.generate_image`.
        """
        parts: list[str] = [self._base_prompt]
        parts.append(f"Scene: {scene}.")

        if clothing:
            parts.append(f"Wearing {clothing}.")

        # Mood / lighting
        mood_map: dict[str, str] = {
            "bright": "bright and airy lighting, soft shadows",
            "golden hour": "golden hour warm sunlight, lens flare",
            "moody": "moody cinematic lighting, rich contrast",
            "soft pastel": "soft pastel tones, gentle diffused light",
            "studio": "professional studio lighting, clean background",
            "neon": "vibrant neon city lights, nighttime ambiance",
        }
        mood_desc = mood_map.get(mood.lower(), mood)
        parts.append(f"Mood: {mood_desc}.")

        parts.append(_QUALITY_SUFFIX)

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Story prompt
    # ------------------------------------------------------------------

    def compose_story_prompt(self, activity: str) -> str:
        """Build a prompt for an Instagram Story image.

        Stories have a more casual, candid aesthetic compared to polished
        feed posts.

        Parameters
        ----------
        activity : str
            What the character is doing,
            e.g. ``"taking a selfie at a bookshop"``.

        Returns
        -------
        str
            A complete prompt string.
        """
        parts: list[str] = [
            self._base_prompt,
            f"Activity: {activity}.",
            "Candid, casual feel, close-up or medium shot,",
            "slight motion blur allowed, authentic moment.",
            _QUALITY_SUFFIX,
        ]
        return " ".join(parts)

    # ------------------------------------------------------------------
    # Seasonal prompt
    # ------------------------------------------------------------------

    def compose_seasonal_prompt(self, season: str, activity: str) -> str:
        """Build a prompt incorporating seasonal elements.

        Parameters
        ----------
        season : str
            One of ``"spring"``, ``"summer"``, ``"autumn"``, ``"winter"``.
        activity : str
            What the character is doing in the seasonal setting.

        Returns
        -------
        str
            A complete prompt string enriched with seasonal details.
        """
        seasonal_elements: dict[str, str] = {
            "spring": (
                "cherry blossom trees in full bloom, soft pink petals falling, "
                "fresh green leaves, warm spring sunlight"
            ),
            "summer": (
                "bright summer sky, lush greenery, sun-drenched scene, "
                "vibrant colors, clear blue sky"
            ),
            "autumn": (
                "golden and red autumn foliage, falling maple leaves, "
                "warm amber tones, cozy autumn atmosphere"
            ),
            "winter": (
                "gentle snowfall, frost-covered surroundings, warm breath visible, "
                "soft winter light, cozy winter layers"
            ),
        }

        season_key = season.lower().strip()
        elements = seasonal_elements.get(season_key, "")

        parts: list[str] = [self._base_prompt]
        if elements:
            parts.append(f"Seasonal setting: {elements}.")
        parts.append(f"Activity: {activity}.")
        parts.append(_QUALITY_SUFFIX)

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Negative prompt
    # ------------------------------------------------------------------

    @staticmethod
    def get_negative_prompt() -> str:
        """Return a negative prompt listing visual artefacts to avoid.

        Returns
        -------
        str
            Comma-separated list of undesirable attributes.
        """
        return _NEGATIVE_PROMPT
