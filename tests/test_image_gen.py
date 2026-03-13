"""Tests for image generation module."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.persona.character import Persona
from src.image_gen.prompt_composer import ImagePromptComposer
from src.image_gen.image_processor import ImageProcessor


class TestImagePromptComposer:
    def setup_method(self):
        self.persona = Persona()
        self.composer = ImagePromptComposer(self.persona)

    def test_feed_prompt_contains_appearance(self):
        prompt = self.composer.compose_feed_prompt("sitting in a cafe")
        assert "Korean" in prompt or "korean" in prompt
        assert "cafe" in prompt.lower()

    def test_feed_prompt_contains_quality(self):
        prompt = self.composer.compose_feed_prompt("walking in park")
        assert "photorealistic" in prompt.lower() or "quality" in prompt.lower()

    def test_story_prompt(self):
        prompt = self.composer.compose_story_prompt("drinking coffee")
        assert "coffee" in prompt.lower()
        assert "candid" in prompt.lower() or "casual" in prompt.lower()

    def test_seasonal_prompt(self):
        prompt = self.composer.compose_seasonal_prompt("spring", "walking")
        assert "spring" in prompt.lower() or "cherry" in prompt.lower() or "blossom" in prompt.lower()

    def test_negative_prompt(self):
        neg = self.composer.get_negative_prompt()
        assert "deformed" in neg.lower() or "blurry" in neg.lower()


class TestImageProcessor:
    def setup_method(self):
        self.processor = ImageProcessor()

    def test_resize_for_feed(self):
        """Test feed resize with a dummy image."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test image
            img = Image.new("RGB", (2000, 2000), color="red")
            test_path = str(Path(tmpdir) / "test.jpg")
            img.save(test_path)

            result = self.processor.resize_for_feed(test_path)
            assert Path(result).exists()

            result_img = Image.open(result)
            assert result_img.size[0] == 1080
            assert result_img.size[1] == 1350

    def test_resize_for_story(self):
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            img = Image.new("RGB", (2000, 3000), color="blue")
            test_path = str(Path(tmpdir) / "test.jpg")
            img.save(test_path)

            result = self.processor.resize_for_story(test_path)
            assert Path(result).exists()

            result_img = Image.open(result)
            assert result_img.size[0] == 1080
            assert result_img.size[1] == 1920
