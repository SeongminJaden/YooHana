#!/usr/bin/env python3
"""Create a test image for Instagram posting test."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image, ImageDraw, ImageFont


def create_test_image(output_path: str | None = None) -> str:
    """Create a simple test image (1080x1350, Instagram feed size).

    Returns the path to the created image.
    """
    width, height = 1080, 1350
    img = Image.new("RGB", (width, height), color=(245, 235, 225))
    draw = ImageDraw.Draw(img)

    # Gradient background (warm beige to soft pink)
    for y in range(height):
        ratio = y / height
        r = int(245 + (255 - 245) * ratio)
        g = int(235 - (235 - 200) * ratio)
        b = int(225 - (225 - 210) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Decorative circles
    import random
    random.seed(42)
    pastel_colors = [
        (255, 182, 193),  # pink
        (173, 216, 230),  # light blue
        (255, 228, 181),  # moccasin
        (221, 160, 221),  # plum
        (176, 224, 230),  # powder blue
    ]
    for _ in range(15):
        x = random.randint(50, width - 50)
        y = random.randint(50, height - 50)
        r = random.randint(20, 80)
        color = random.choice(pastel_colors)
        alpha_color = (*color, 100)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline=None)

    # Text
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large

    # Main text
    title = "AI Influencer Test"
    bbox = draw.textbbox((0, 0), title, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, height // 2 - 80), title,
              fill=(80, 60, 80), font=font_large)

    subtitle = "Yoo Hana"
    bbox2 = draw.textbbox((0, 0), subtitle, font=font_medium)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((width - tw2) // 2, height // 2 - 20), subtitle,
              fill=(120, 90, 120), font=font_medium)

    # Emoji-like decorations
    deco = "~ test post ~"
    bbox3 = draw.textbbox((0, 0), deco, font=font_small)
    tw3 = bbox3[2] - bbox3[0]
    draw.text(((width - tw3) // 2, height // 2 + 30), deco,
              fill=(150, 120, 150), font=font_small)

    # Save
    if output_path is None:
        output_dir = PROJECT_ROOT / "outputs" / "images"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / "test_post.jpg")

    img.save(output_path, "JPEG", quality=95)
    print(f"Test image created: {output_path}")
    return output_path


if __name__ == "__main__":
    create_test_image()
