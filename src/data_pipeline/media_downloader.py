"""Download and analyze media (images/videos) from crawled Instagram posts."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MEDIA_DIR = _PROJECT_ROOT / "data" / "media"
_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def download_image(url: str, save_dir: Path = _MEDIA_DIR) -> Path | None:
    """Download an image from URL and return the local path."""
    try:
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        ext = ".jpg"
        if ".png" in url:
            ext = ".png"
        elif ".webp" in url:
            ext = ".webp"
        path = save_dir / f"img_{h}{ext}"
        if path.exists():
            return path

        resp = requests.get(url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
        })
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return path
    except Exception as exc:
        logger.debug("Failed to download image: {}", exc)
        return None


def download_video(url: str, save_dir: Path = _MEDIA_DIR) -> Path | None:
    """Download a video from URL and return the local path."""
    try:
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        path = save_dir / f"vid_{h}.mp4"
        if path.exists():
            return path

        resp = requests.get(url, timeout=30, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
        })
        resp.raise_for_status()
        with open(path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return path
    except Exception as exc:
        logger.debug("Failed to download video: {}", exc)
        return None


def analyze_image(path: Path) -> dict[str, Any]:
    """Analyze an image and return basic visual properties."""
    info: dict[str, Any] = {"path": str(path)}
    try:
        img = Image.open(path)
        info["width"] = img.width
        info["height"] = img.height
        info["aspect_ratio"] = round(img.width / img.height, 2)
        info["format"] = img.format or path.suffix.lstrip(".")
        info["mode"] = img.mode  # RGB, RGBA, etc.

        # Orientation
        if img.width > img.height:
            info["orientation"] = "landscape"
        elif img.height > img.width:
            info["orientation"] = "portrait"
        else:
            info["orientation"] = "square"

        # Dominant colors (sample center region)
        thumb = img.copy()
        thumb.thumbnail((100, 100))
        if thumb.mode != "RGB":
            thumb = thumb.convert("RGB")
        pixels = list(thumb.getdata())

        # Average color
        r_avg = sum(p[0] for p in pixels) // len(pixels)
        g_avg = sum(p[1] for p in pixels) // len(pixels)
        b_avg = sum(p[2] for p in pixels) // len(pixels)
        info["avg_color_rgb"] = [r_avg, g_avg, b_avg]

        # Brightness (0-255)
        brightness = (r_avg * 299 + g_avg * 587 + b_avg * 114) // 1000
        info["brightness"] = brightness
        if brightness > 180:
            info["tone"] = "bright"
        elif brightness > 100:
            info["tone"] = "medium"
        else:
            info["tone"] = "dark"

        # Color temperature estimate
        if r_avg > b_avg + 30:
            info["temperature"] = "warm"
        elif b_avg > r_avg + 30:
            info["temperature"] = "cool"
        else:
            info["temperature"] = "neutral"

        # Saturation estimate
        max_c = max(r_avg, g_avg, b_avg)
        min_c = min(r_avg, g_avg, b_avg)
        if max_c > 0:
            sat = (max_c - min_c) / max_c
        else:
            sat = 0
        info["saturation"] = round(sat, 2)
        if sat > 0.5:
            info["color_style"] = "vivid"
        elif sat > 0.2:
            info["color_style"] = "natural"
        else:
            info["color_style"] = "muted"

        img.close()
    except Exception as exc:
        info["error"] = str(exc)

    return info


def _get_ffprobe_path() -> str:
    """Get ffprobe path, trying system then imageio_ffmpeg."""
    import shutil
    path = shutil.which("ffprobe")
    if path:
        return path
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        # ffprobe is next to ffmpeg
        probe = ff.replace("ffmpeg", "ffprobe")
        if Path(probe).exists():
            return probe
        # Some installs only have ffmpeg - use it with -show_format trick
        return ff
    except ImportError:
        return "ffprobe"


def _get_ffmpeg_path() -> str:
    """Get ffmpeg path, trying system then imageio_ffmpeg."""
    import shutil
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def analyze_video_basic(path: Path) -> dict[str, Any]:
    """Analyze a video file for basic properties."""
    import subprocess
    info: dict[str, Any] = {"path": str(path)}

    try:
        ffprobe = _get_ffprobe_path()
        # If we only have ffmpeg (not ffprobe), use ffmpeg -i
        if "ffprobe" not in ffprobe and "ffmpeg" in ffprobe:
            return _analyze_video_with_ffmpeg(path, ffprobe)

        result = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            import json
            probe = json.loads(result.stdout)

            # Format info
            fmt = probe.get("format", {})
            info["duration_sec"] = round(float(fmt.get("duration", 0)), 1)
            info["size_mb"] = round(int(fmt.get("size", 0)) / 1048576, 2)

            # Stream info
            for stream in probe.get("streams", []):
                if stream["codec_type"] == "video":
                    info["width"] = int(stream.get("width", 0))
                    info["height"] = int(stream.get("height", 0))
                    info["codec"] = stream.get("codec_name", "")
                    fps_str = stream.get("r_frame_rate", "30/1")
                    if "/" in fps_str:
                        num, den = fps_str.split("/")
                        info["fps"] = round(int(num) / max(int(den), 1), 1)

                    if info["width"] > info["height"]:
                        info["orientation"] = "landscape"
                    elif info["height"] > info["width"]:
                        info["orientation"] = "portrait"
                    else:
                        info["orientation"] = "square"

                elif stream["codec_type"] == "audio":
                    info["has_audio"] = True
                    info["audio_codec"] = stream.get("codec_name", "")

            if "has_audio" not in info:
                info["has_audio"] = False

            # Duration category
            dur = info.get("duration_sec", 0)
            if dur <= 15:
                info["duration_category"] = "short"
            elif dur <= 60:
                info["duration_category"] = "medium"
            else:
                info["duration_category"] = "long"

    except FileNotFoundError:
        # Try ffmpeg fallback
        try:
            ffmpeg = _get_ffmpeg_path()
            return _analyze_video_with_ffmpeg(path, ffmpeg)
        except Exception:
            info["error"] = "ffprobe/ffmpeg not found"
            info["size_mb"] = round(path.stat().st_size / 1048576, 2)
    except Exception as exc:
        info["error"] = str(exc)

    return info


def _analyze_video_with_ffmpeg(path: Path, ffmpeg_path: str) -> dict[str, Any]:
    """Analyze video using ffmpeg -i (when ffprobe is not available)."""
    import subprocess
    info: dict[str, Any] = {"path": str(path)}
    info["size_mb"] = round(path.stat().st_size / 1048576, 2)

    result = subprocess.run(
        [ffmpeg_path, "-i", str(path)],
        capture_output=True, text=True, timeout=15
    )
    # ffmpeg -i outputs info to stderr
    output = result.stderr

    # Duration: Duration: 00:00:15.23
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", output)
    if dur_match:
        h, m, s, ms = dur_match.groups()
        info["duration_sec"] = round(int(h)*3600 + int(m)*60 + int(s) + int(ms)/100, 1)

    # Video stream: Stream #0:0: Video: h264, 1080x1920, 30 fps
    vid_match = re.search(r"Video:\s*(\w+).*?,\s*(\d+)x(\d+)", output)
    if vid_match:
        info["codec"] = vid_match.group(1)
        info["width"] = int(vid_match.group(2))
        info["height"] = int(vid_match.group(3))
        if info["width"] > info["height"]:
            info["orientation"] = "landscape"
        elif info["height"] > info["width"]:
            info["orientation"] = "portrait"
        else:
            info["orientation"] = "square"

    # FPS
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", output)
    if fps_match:
        info["fps"] = float(fps_match.group(1))

    # Audio
    audio_match = re.search(r"Audio:\s*(\w+)", output)
    info["has_audio"] = audio_match is not None
    if audio_match:
        info["audio_codec"] = audio_match.group(1)

    # Duration category
    dur = info.get("duration_sec", 0)
    if dur <= 15:
        info["duration_category"] = "short"
    elif dur <= 60:
        info["duration_category"] = "medium"
    else:
        info["duration_category"] = "long"

    return info


def extract_thumbnail_from_video(path: Path, timestamp: float = 1.0) -> Path | None:
    """Extract a thumbnail frame from a video using ffmpeg."""
    import subprocess
    thumb_path = path.with_suffix(".thumb.jpg")
    if thumb_path.exists():
        return thumb_path
    try:
        ffmpeg = _get_ffmpeg_path()
        subprocess.run(
            [ffmpeg, "-y", "-ss", str(timestamp), "-i", str(path),
             "-frames:v", "1", "-q:v", "2", str(thumb_path)],
            capture_output=True, timeout=10
        )
        if thumb_path.exists():
            return thumb_path
    except Exception:
        pass
    return None
