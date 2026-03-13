"""
Image post-processing for the AI Influencer.

Provides resizing, filtering, and compression utilities so that
generated images meet Instagram upload requirements and maintain
a consistent visual aesthetic.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "outputs" / "images"

# Instagram standard dimensions
_FEED_SIZE = (1080, 1350)   # 4:5 portrait
_STORY_SIZE = (1080, 1920)  # 9:16 vertical


def _ensure_output_dir(output_dir: Path | None = None) -> Path:
    """Return the resolved output directory, creating it if necessary."""
    out = output_dir or _DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return out


def _processed_path(
    original: Path,
    suffix_tag: str,
    output_dir: Path | None = None,
) -> Path:
    """Build a destination path for a processed image.

    ``<stem>_<suffix_tag>.jpg`` inside *output_dir*.
    """
    out = _ensure_output_dir(output_dir)
    return out / f"{original.stem}_{suffix_tag}.jpg"


def _resize_and_crop_center(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> Image.Image:
    """Resize while maintaining aspect ratio, then center-crop to target.

    The image is first scaled so that it fully covers the target
    dimensions, then the excess is cropped equally from both sides.
    """
    src_w, src_h = img.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        # Source is wider: scale by height, crop width
        new_h = target_h
        new_w = int(src_w * (target_h / src_h))
    else:
        # Source is taller: scale by width, crop height
        new_w = target_w
        new_h = int(src_h * (target_w / src_w))

    img_resized = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    right = left + target_w
    bottom = top + target_h

    return img_resized.crop((left, top, right, bottom))


class ImageProcessor:
    """Post-processing pipeline for AI-generated images.

    All public methods accept a file path, process the image, save the
    result under ``outputs/images/``, and return the path to the new file.

    Parameters
    ----------
    output_dir : str | Path | None
        Base directory for processed images.  Defaults to
        ``<project_root>/outputs/images/``.
    """

    def __init__(self, output_dir: str | Path | None = None) -> None:
        if output_dir is not None:
            self._output_dir = Path(output_dir)
            if not self._output_dir.is_absolute():
                self._output_dir = _PROJECT_ROOT / self._output_dir
        else:
            self._output_dir = _DEFAULT_OUTPUT_DIR

    # ------------------------------------------------------------------
    # Resizing
    # ------------------------------------------------------------------

    def resize_for_feed(self, image_path: str) -> str:
        """Resize and center-crop an image to Instagram feed size (1080x1350).

        Parameters
        ----------
        image_path : str
            Path to the source image.

        Returns
        -------
        str
            Absolute path to the resized image.
        """
        src = Path(image_path)
        img = Image.open(src).convert("RGB")
        result = _resize_and_crop_center(img, *_FEED_SIZE)

        dest = _processed_path(src, "feed", self._output_dir)
        result.save(dest, "JPEG", quality=95)

        logger.info("Resized for feed ({}) -> {}", _FEED_SIZE, dest)
        return str(dest)

    def resize_for_story(self, image_path: str) -> str:
        """Resize and center-crop an image to Instagram Story size (1080x1920).

        Parameters
        ----------
        image_path : str
            Path to the source image.

        Returns
        -------
        str
            Absolute path to the resized image.
        """
        src = Path(image_path)
        img = Image.open(src).convert("RGB")
        result = _resize_and_crop_center(img, *_STORY_SIZE)

        dest = _processed_path(src, "story", self._output_dir)
        result.save(dest, "JPEG", quality=95)

        logger.info("Resized for story ({}) -> {}", _STORY_SIZE, dest)
        return str(dest)

    # ------------------------------------------------------------------
    # Filters
    # ------------------------------------------------------------------

    def add_subtle_filter(
        self,
        image_path: str,
        filter_name: str = "warm",
    ) -> str:
        """Apply a subtle color adjustment filter to an image.

        Parameters
        ----------
        image_path : str
            Path to the source image.
        filter_name : str
            Filter preset name.  Supported values:

            * ``"warm"`` -- slight warm tone shift (increased reds/yellows).
            * ``"cool"`` -- slight cool tone shift (increased blues).
            * ``"vivid"`` -- boosted saturation and contrast.
            * ``"soft"`` -- reduced contrast, gentle blur.

        Returns
        -------
        str
            Absolute path to the filtered image.
        """
        src = Path(image_path)
        img = Image.open(src).convert("RGB")

        filter_key = filter_name.lower().strip()

        if filter_key == "warm":
            # Warm tone: slight red/yellow boost
            r, g, b = img.split()
            r = r.point(lambda v: min(255, int(v * 1.08)))
            g = g.point(lambda v: min(255, int(v * 1.02)))
            img = Image.merge("RGB", (r, g, b))
            img = ImageEnhance.Color(img).enhance(1.05)

        elif filter_key == "cool":
            # Cool tone: slight blue boost
            r, g, b = img.split()
            b = b.point(lambda v: min(255, int(v * 1.10)))
            r = r.point(lambda v: min(255, int(v * 0.95)))
            img = Image.merge("RGB", (r, g, b))
            img = ImageEnhance.Color(img).enhance(1.03)

        elif filter_key == "vivid":
            # Vivid: boosted saturation and contrast
            img = ImageEnhance.Color(img).enhance(1.20)
            img = ImageEnhance.Contrast(img).enhance(1.10)

        elif filter_key == "soft":
            # Soft: reduced contrast, gentle smoothing
            img = ImageEnhance.Contrast(img).enhance(0.90)
            img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
            img = ImageEnhance.Brightness(img).enhance(1.03)

        else:
            logger.warning(
                "Unknown filter '{}', returning image unmodified.", filter_name
            )

        dest = _processed_path(src, f"filter_{filter_key}", self._output_dir)
        img.save(dest, "JPEG", quality=95)

        logger.info("Applied '{}' filter -> {}", filter_key, dest)
        return str(dest)

    # ------------------------------------------------------------------
    # Compression / optimization
    # ------------------------------------------------------------------

    def optimize_for_upload(
        self,
        image_path: str,
        max_size_kb: int = 1000,
    ) -> str:
        """Compress an image to stay under a target file size.

        The quality is iteratively reduced until the JPEG output is
        smaller than *max_size_kb* kilobytes.

        Parameters
        ----------
        image_path : str
            Path to the source image.
        max_size_kb : int
            Maximum allowed file size in kilobytes.

        Returns
        -------
        str
            Absolute path to the optimised image.
        """
        src = Path(image_path)
        img = Image.open(src).convert("RGB")

        dest = _processed_path(src, "optimized", self._output_dir)
        max_bytes = max_size_kb * 1024

        quality = 95
        while quality >= 10:
            img.save(dest, "JPEG", quality=quality, optimize=True)
            size = dest.stat().st_size
            if size <= max_bytes:
                break
            quality -= 5

        final_kb = dest.stat().st_size / 1024
        logger.info(
            "Optimised for upload (quality={}, {:.1f} KB) -> {}",
            quality,
            final_kb,
            dest,
        )
        return str(dest)
