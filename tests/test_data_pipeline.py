"""Tests for data pipeline module."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_pipeline.cleaner import DataCleaner


class TestDataCleaner:
    def setup_method(self):
        self.cleaner = DataCleaner()

    def test_remove_mentions(self):
        text = "오늘 @friend 와 카페 갔어"
        cleaned = self.cleaner.clean_caption(text)
        assert "@friend" not in cleaned

    def test_remove_urls(self):
        text = "여기 추천 https://example.com 진짜 좋아"
        cleaned = self.cleaner.clean_caption(text)
        assert "https://" not in cleaned

    def test_remove_excessive_hashtags(self):
        text = "좋은 하루 #일상 #카페 #오늘 #좋아 #하루"
        cleaned = self.cleaner.clean_caption(text)
        # Excessive hashtags (4+) should be removed
        assert cleaned.count("#") < 4 or "#" not in cleaned

    def test_normalize_whitespace(self):
        text = "오늘   정말   좋은   하루"
        cleaned = self.cleaner.clean_caption(text)
        assert "   " not in cleaned

    def test_filter_quality_min_length(self):
        captions = [
            {"text": "짧음"},
            {"text": "이것은 충분히 긴 캡션입니다 오늘 하루도 즐겁게 보냈어"},
        ]
        filtered = self.cleaner.filter_quality(captions, min_length=10)
        assert len(filtered) == 1
        assert "충분히" in filtered[0]["text"]

    def test_remove_duplicates(self):
        captions = [
            {"text": "같은 캡션"},
            {"text": "다른 캡션"},
            {"text": "같은 캡션"},
        ]
        deduped = self.cleaner.remove_duplicates(captions)
        assert len(deduped) == 2

    def test_process_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test input
            input_dir = Path(tmpdir) / "raw"
            input_dir.mkdir()
            test_data = [
                {"text": "테스트 캡션입니다 오늘 하루 좋은 날", "source": "test", "likes": 10, "timestamp": "2024-01-01"},
                {"text": "짧음", "source": "test", "likes": 5, "timestamp": "2024-01-01"},
            ]
            with open(input_dir / "test.json", "w") as f:
                json.dump(test_data, f, ensure_ascii=False)

            output_path = Path(tmpdir) / "output.jsonl"
            self.cleaner.process_all(str(input_dir), str(output_path))

            assert output_path.exists()
            with open(output_path) as f:
                lines = f.readlines()
            assert len(lines) >= 1
