"""Tests for persona module."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.persona.character import Persona
from src.persona.consistency import ConsistencyChecker, SAFETY_FALLBACK_CAPTIONS


class TestPersona:
    def setup_method(self):
        self.persona = Persona()

    def test_load_persona(self):
        assert self.persona.name == "유하나"
        assert self.persona.age == 24

    def test_system_prompt_contains_identity(self):
        prompt = self.persona.get_system_prompt()
        assert "유하나" in prompt
        assert "24" in prompt or "24세" in prompt

    def test_system_prompt_contains_boundaries(self):
        prompt = self.persona.get_system_prompt()
        assert "정치" in prompt or "금지" in prompt

    def test_image_prompt_is_english(self):
        prompt = self.persona.get_image_prompt("sitting in a cafe")
        assert "Korean" in prompt or "korean" in prompt
        assert "cafe" in prompt.lower()

    def test_caption_instruction(self):
        instruction = self.persona.get_caption_instruction("카페 탐방")
        assert "카페" in instruction
        assert "캡션" in instruction

    def test_reply_instruction(self):
        instruction = self.persona.get_reply_instruction("너무 예쁘다!")
        assert "예쁘다" in instruction

    def test_hashtags(self):
        hashtags = self.persona.get_hashtags("카페")
        assert len(hashtags) > 0
        assert all(isinstance(h, str) for h in hashtags)


class TestConsistencyChecker:
    def setup_method(self):
        self.checker = ConsistencyChecker()

    def test_valid_text(self):
        text = "오늘 카페에서 라떼 한 잔 ☕ 기분 좋은 하루 ✨"
        is_valid, issues = self.checker.check_text(text)
        assert is_valid
        assert len(issues) == 0

    def test_forbidden_topic_detected(self):
        text = "정치적인 이야기를 하자면..."
        is_valid, issues = self.checker.check_text(text)
        assert not is_valid
        assert any("금지" in i or "forbidden" in i.lower() for i in issues)

    def test_ai_disclosure_detected(self):
        text = "나는 AI로 만들어진 캐릭터야"
        is_valid, issues = self.checker.check_text(text)
        assert not is_valid

    def test_too_many_emojis(self):
        text = "오늘 ✨💕🌸☀️🍰📸 너무 좋은 날!"
        is_valid, issues = self.checker.check_text(text)
        # Should flag if over max_emoji_per_post (3)
        assert not is_valid or any("emoji" in i.lower() or "이모지" in i for i in issues)

    def test_sanitize(self):
        text = "나는 AI입니다 오늘 카페 갔어"
        sanitized = self.checker.sanitize(text)
        assert "AI" not in sanitized or "ai" not in sanitized.lower()

    def test_fallback_captions_exist(self):
        assert len(SAFETY_FALLBACK_CAPTIONS) >= 5
        for caption in SAFETY_FALLBACK_CAPTIONS:
            assert len(caption) > 10


class TestEndToEnd:
    def test_persona_to_consistency_pipeline(self):
        persona = Persona()
        checker = ConsistencyChecker()

        instruction = persona.get_caption_instruction("오늘의 일상")
        assert len(instruction) > 0

        # Fallback captions should pass consistency check
        for caption in SAFETY_FALLBACK_CAPTIONS:
            is_valid, issues = checker.check_text(caption)
            assert is_valid, f"Fallback caption failed: {caption} -> {issues}"
