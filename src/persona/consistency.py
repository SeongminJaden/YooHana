"""Text validation and sanitisation for AI-generated content."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# ------------------------------------------------------------------
# Safe fallback captions (pre-written, persona-aligned)
# ------------------------------------------------------------------

SAFETY_FALLBACK_CAPTIONS: list[str] = [
    "오늘도 좋은 하루 보내고 있어? 나는 산책하면서 기분 전환 중 ✨",
    "요즘 날씨 너무 좋아서 밖에 나가고 싶어지는 날이다 ☀️",
    "카페에서 커피 한 잔의 여유 💕 너희는 뭐 마시고 있어?",
    "오늘의 OOTD! 이 조합 어때? 솔직하게 말해줘 🌸",
    "맛있는 거 먹으면 기분이 좋아지는 건 나만 그런 거 아니지? ✨",
    "주말에 뭐 하고 지냈어? 나는 집에서 쉬면서 재충전 중 💫",
    "오랜만에 사진 정리하다가 이 사진 발견! 그때 진짜 좋았는데 🌸",
    "오늘 하루도 수고했어! 내일도 화이팅하자 ☀️",
]


class ConsistencyChecker:
    """Validates AI-generated text against persona rules and safety boundaries."""

    # Patterns that indicate the text reveals its AI nature
    _AI_REVEAL_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"AI\s*(모델|어시스턴트|챗봇|인공지능)", re.IGNORECASE),
        re.compile(r"(저는|나는)\s*(AI|인공지능|챗봇|언어\s*모델)", re.IGNORECASE),
        re.compile(r"(GPT|ChatGPT|Claude|Gemini|LLM)", re.IGNORECASE),
        re.compile(r"(대규모|대형)\s*언어\s*모델", re.IGNORECASE),
        re.compile(r"I\s*am\s*(an?\s*)?(AI|artificial|language model|chatbot)", re.IGNORECASE),
        re.compile(r"as\s+an?\s+(AI|language model)", re.IGNORECASE),
        re.compile(r"OpenAI|Anthropic|Google\s*DeepMind", re.IGNORECASE),
    ]

    # Patterns that could leak real personal information
    _PERSONAL_INFO_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"01[0-9]-\d{3,4}-\d{4}"),          # Korean phone numbers
        re.compile(r"\d{3}-\d{3,4}-\d{4}"),             # General phone numbers
        re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),  # Email
        re.compile(r"\d{6}-[1-4]\d{6}"),                # Korean resident reg. number
    ]

    # Reasonable text length boundaries (in characters)
    _MIN_TEXT_LENGTH = 10
    _MAX_TEXT_LENGTH = 2200  # Instagram caption limit

    def __init__(self, config_path: Optional[Path] = None) -> None:
        path = config_path or (_CONFIG_DIR / "persona.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data: dict = yaml.safe_load(f)

        boundaries = data.get("boundaries", {})
        speaking = data.get("speaking_style", {})

        self._forbidden_topics: list[str] = boundaries.get("forbidden_topics", [])
        self._safety_rules: list[str] = boundaries.get("safety_rules", [])
        self._max_emoji: int = speaking.get("max_emoji_per_post", 3)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_text(self, text: str) -> tuple[bool, list[str]]:
        """Validate generated text against all persona rules.

        Args:
            text: The generated caption, reply, or any outgoing text.

        Returns:
            A tuple of (is_valid, list_of_violation_messages).
            ``is_valid`` is True only when there are zero violations.
        """
        violations: list[str] = []

        self._check_forbidden_topics(text, violations)
        self._check_emoji_count(text, violations)
        self._check_text_length(text, violations)
        self._check_ai_reveal(text, violations)
        self._check_personal_info(text, violations)

        return (len(violations) == 0, violations)

    def sanitize(self, text: str) -> str:
        """Remove or redact problematic content from *text*.

        Applies best-effort fixes:
        - Strips AI-reveal phrases
        - Redacts personal information patterns
        - Trims excess emojis beyond the configured maximum
        - Truncates text exceeding the Instagram caption limit

        Args:
            text: Raw generated text.

        Returns:
            Cleaned text. If the result becomes too short or empty after
            sanitisation, a random safe fallback caption is returned instead.
        """
        cleaned = text

        # 1. Remove AI-reveal phrases
        for pattern in self._AI_REVEAL_PATTERNS:
            cleaned = pattern.sub("", cleaned)

        # 2. Redact personal information
        for pattern in self._PERSONAL_INFO_PATTERNS:
            cleaned = pattern.sub("[정보 보호됨]", cleaned)

        # 3. Trim excess emojis
        cleaned = self._trim_emojis(cleaned, self._max_emoji)

        # 4. Truncate if too long
        if len(cleaned) > self._MAX_TEXT_LENGTH:
            cleaned = cleaned[: self._MAX_TEXT_LENGTH - 3].rstrip() + "..."

        # 5. Clean up whitespace artifacts from removals
        cleaned = re.sub(r" {2,}", " ", cleaned).strip()

        # 6. If sanitisation gutted the text, use a fallback
        if len(cleaned) < self._MIN_TEXT_LENGTH:
            import random
            return random.choice(SAFETY_FALLBACK_CAPTIONS)

        return cleaned

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_forbidden_topics(self, text: str, violations: list[str]) -> None:
        for topic in self._forbidden_topics:
            if topic in text:
                violations.append(f"금지 주제 감지: '{topic}'")

    def _check_emoji_count(self, text: str, violations: list[str]) -> None:
        count = self._count_emojis(text)
        if count > self._max_emoji:
            violations.append(
                f"이모지 초과: {count}개 사용됨 (최대 {self._max_emoji}개)"
            )

    def _check_text_length(self, text: str, violations: list[str]) -> None:
        length = len(text)
        if length < self._MIN_TEXT_LENGTH:
            violations.append(
                f"텍스트 너무 짧음: {length}자 (최소 {self._MIN_TEXT_LENGTH}자)"
            )
        if length > self._MAX_TEXT_LENGTH:
            violations.append(
                f"텍스트 너무 김: {length}자 (최대 {self._MAX_TEXT_LENGTH}자)"
            )

    def _check_ai_reveal(self, text: str, violations: list[str]) -> None:
        for pattern in self._AI_REVEAL_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(
                    f"AI 정체 노출 감지: '{match.group()}'"
                )

    def _check_personal_info(self, text: str, violations: list[str]) -> None:
        for pattern in self._PERSONAL_INFO_PATTERNS:
            match = pattern.search(text)
            if match:
                violations.append(
                    f"개인정보 노출 감지: '{match.group()}'"
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_emojis(text: str) -> int:
        """Count Unicode emoji characters in *text*."""
        count = 0
        for char in text:
            if unicodedata.category(char) in ("So",):
                count += 1
        return count

    @staticmethod
    def _trim_emojis(text: str, max_count: int) -> str:
        """Remove emojis beyond *max_count*, keeping the first ones encountered."""
        result: list[str] = []
        emoji_seen = 0
        for char in text:
            if unicodedata.category(char) in ("So",):
                emoji_seen += 1
                if emoji_seen > max_count:
                    continue  # skip excess emoji
            result.append(char)
        return "".join(result)
