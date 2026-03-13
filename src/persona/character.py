"""Persona definition and prompt generation for the AI Influencer."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class Persona:
    """Loads persona.yaml and exposes identity, appearance, and prompt helpers."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        path = config_path or (_CONFIG_DIR / "persona.yaml")
        with open(path, "r", encoding="utf-8") as f:
            self._data: dict = yaml.safe_load(f)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._data["identity"]["name"]

    @property
    def name_en(self) -> str:
        return self._data["identity"]["name_en"]

    @property
    def age(self) -> int:
        return self._data["identity"]["age"]

    @property
    def appearance_prompt(self) -> str:
        """English base prompt used for image generation."""
        return self._data["appearance"]["image_prompt_base"].strip()

    @property
    def system_prompt(self) -> str:
        """Korean system prompt assembled from personality and speaking style."""
        return self.get_system_prompt()

    @property
    def forbidden_topics(self) -> list[str]:
        return self._data["boundaries"]["forbidden_topics"]

    @property
    def max_emoji_per_post(self) -> int:
        return self._data["speaking_style"]["max_emoji_per_post"]

    # ------------------------------------------------------------------
    # Image prompt
    # ------------------------------------------------------------------

    def get_image_prompt(self, scene: str, style: str = "casual") -> str:
        """Combine the base appearance prompt with a scene description and style.

        Args:
            scene: Scene or setting description, e.g. "sitting in a cozy cafe".
            style: Visual/fashion style modifier, e.g. "casual", "formal", "sporty".

        Returns:
            A full English prompt ready for an image-generation model.
        """
        style_map: dict[str, str] = {
            "casual": "casual chic outfit, relaxed vibe",
            "formal": "elegant formal outfit, sophisticated look",
            "sporty": "athleisure wear, energetic vibe",
            "cozy": "cozy knitwear, warm and comfortable",
            "summer": "light summer outfit, bright and fresh",
            "winter": "stylish winter layers, warm accessories",
        }
        style_desc = style_map.get(style, style)

        return (
            f"{self.appearance_prompt} "
            f"Scene: {scene}. "
            f"Style: {style_desc}. "
            f"Natural lighting, shallow depth of field, 4K quality."
        )

    # ------------------------------------------------------------------
    # LLM system prompt (Korean)
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        """Build a Korean system prompt encoding personality, speaking style, and boundaries."""
        identity = self._data["identity"]
        personality = self._data["personality"]
        speaking = self._data["speaking_style"]
        boundaries = self._data["boundaries"]

        traits = ", ".join(personality["traits"])
        speaking_features = "\n".join(f"  - {f}" for f in speaking["features"])
        forbidden = ", ".join(boundaries["forbidden_topics"])
        safety_rules = "\n".join(f"  - {r}" for r in boundaries["safety_rules"])

        return (
            f"너는 '{identity['name']}' ({identity['name_en']})이야.\n"
            f"나이: {identity['age']}세 / 직업: {identity['occupation']}\n"
            f"위치: {identity['location']}\n\n"
            f"[성격]\n"
            f"MBTI: {personality['mbti']}\n"
            f"성격 특성: {traits}\n"
            f"분위기: {personality['mood']}\n\n"
            f"[말투]\n"
            f"언어: {speaking['language']}\n"
            f"톤: {speaking['tone']}\n"
            f"특징:\n{speaking_features}\n"
            f"이모지는 게시글 당 최대 {speaking['max_emoji_per_post']}개까지만 사용해.\n\n"
            f"[금지 주제]\n"
            f"{forbidden}\n\n"
            f"[안전 규칙]\n"
            f"{safety_rules}\n\n"
            f"절대 AI라는 사실을 언급하지 마. "
            f"항상 {identity['name']}의 캐릭터를 유지해."
        )

    # ------------------------------------------------------------------
    # Caption instruction
    # ------------------------------------------------------------------

    def get_caption_instruction(self, topic: str) -> str:
        """Generate an instruction for the LLM to write an Instagram caption.

        Args:
            topic: The topic or theme of the post, e.g. "카페 탐방".

        Returns:
            A Korean instruction string to be appended after the system prompt.
        """
        speaking = self._data["speaking_style"]
        emoji_favs = " ".join(speaking["emoji_favorites"][:5])

        return (
            f"아래 주제로 인스타그램 캡션을 작성해줘.\n\n"
            f"주제: {topic}\n\n"
            f"조건:\n"
            f"- {self.name}의 말투와 성격을 유지할 것\n"
            f"- 이모지 최대 {self.max_emoji_per_post}개 (추천: {emoji_favs})\n"
            f"- 자연스럽고 친근한 톤\n"
            f"- 팔로워에게 질문을 던져 소통 유도\n"
            f"- 해시태그는 포함하지 말 것 (별도 생성)"
        )

    # ------------------------------------------------------------------
    # Reply instruction
    # ------------------------------------------------------------------

    def get_reply_instruction(self, comment: str) -> str:
        """Generate an instruction for the LLM to reply to a follower comment.

        Args:
            comment: The original comment text from a follower.

        Returns:
            A Korean instruction string for generating a reply.
        """
        return (
            f"팔로워의 댓글에 답글을 작성해줘.\n\n"
            f"댓글: \"{comment}\"\n\n"
            f"조건:\n"
            f"- {self.name}의 말투와 성격을 유지할 것\n"
            f"- 짧고 친근하게 (1-2문장)\n"
            f"- 이모지 최대 1개\n"
            f"- 상대방에게 관심을 보여줄 것\n"
            f"- 절대 AI임을 드러내지 말 것"
        )

    # ------------------------------------------------------------------
    # Hashtag suggestions
    # ------------------------------------------------------------------

    def get_hashtags(self, theme: str) -> list[str]:
        """Suggest relevant hashtags for a given theme.

        Combines persona-specific base hashtags with theme-specific ones.
        Seasonal keywords from the config are incorporated when they match.

        Args:
            theme: Post theme, e.g. "카페", "봄 코디", "OOTD".

        Returns:
            A list of hashtag strings (with leading #).
        """
        identity = self._data["identity"]
        content_themes = self._data["content_themes"]

        # Base hashtags that always apply
        base: list[str] = [
            f"#{identity['name_en'].replace(' ', '')}",
            "#일상",
            "#daily",
            "#서울",
            "#Seoul",
        ]

        # Theme-specific hashtags
        theme_lower = theme.lower()
        theme_tags: list[str] = [f"#{theme.replace(' ', '')}"]

        # Map common themes to extra hashtags
        theme_map: dict[str, list[str]] = {
            "카페": ["#카페스타그램", "#cafehopping", "#커피", "#카페추천"],
            "패션": ["#OOTD", "#패션스타그램", "#데일리룩", "#코디"],
            "ootd": ["#OOTD", "#패션스타그램", "#데일리룩", "#오오티디"],
            "맛집": ["#맛집", "#먹스타그램", "#foodie", "#맛집추천"],
            "여행": ["#여행스타그램", "#travel", "#여행", "#trip"],
            "자기계발": ["#자기계발", "#성장", "#motivation", "#영감"],
            "음악": ["#음악", "#music", "#플레이리스트", "#감성"],
        }

        for key, tags in theme_map.items():
            if key in theme_lower:
                theme_tags.extend(tags)
                break

        # Seasonal keyword matching
        seasonal = content_themes.get("seasonal", {})
        for _season, keywords in seasonal.items():
            for kw in keywords:
                if kw in theme:
                    theme_tags.append(f"#{kw.replace(' ', '')}")

        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for tag in base + theme_tags:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)

        return result[:10]  # Keep within recommended 5-10 range
