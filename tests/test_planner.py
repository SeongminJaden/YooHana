"""Tests for planner module."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.persona.character import Persona
from src.planner.topic_generator import TopicGenerator


class TestTopicGenerator:
    def setup_method(self):
        self.persona = Persona()
        self.gen = TopicGenerator(self.persona)

    def test_generate_topics(self):
        topics = self.gen.generate_topics(count=5)
        assert len(topics) == 5
        assert all(isinstance(t, str) for t in topics)
        assert all(len(t) > 0 for t in topics)

    def test_generate_topics_with_theme(self):
        topics = self.gen.generate_topics(count=3, theme="카페")
        assert len(topics) == 3

    def test_generate_hashtags(self):
        hashtags = self.gen.generate_hashtags("카페 탐방")
        assert len(hashtags) > 0
        assert len(hashtags) <= 10

    def test_seasonal_topics(self):
        topics = self.gen.get_seasonal_topics()
        assert isinstance(topics, list)
        assert len(topics) > 0

    def test_korean_holidays(self):
        holidays = self.gen.get_korean_holidays()
        assert isinstance(holidays, list)
        for h in holidays:
            assert "name" in h
            assert "date" in h
