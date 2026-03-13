"""
Reel content creation for the AI Influencer.

Generates image frames, captions, and composes them into short-form
video reels with transitions and optional music.  Uses ffmpeg-python
for video composition and delegates image generation and text writing
to the injected ``image_client`` and ``text_generator`` collaborators.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

from src.persona.character import Persona
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REEL_DIR = _PROJECT_ROOT / "outputs" / "reels"
_DEFAULT_FRAME_DIR = _PROJECT_ROOT / "outputs" / "reel_frames"


# ---------------------------------------------------------------------------
# Lazy ffmpeg import
# ---------------------------------------------------------------------------


def _import_ffmpeg() -> Any:
    """Import ffmpeg-python lazily, returning ``None`` on failure."""
    try:
        import ffmpeg  # type: ignore[import-untyped]
        return ffmpeg
    except ImportError:
        logger.warning(
            "ffmpeg-python is not installed – video composition "
            "features will be unavailable."
        )
        return None


# ---------------------------------------------------------------------------
# ReelCreator
# ---------------------------------------------------------------------------


class ReelCreator:
    """Generate and compose Instagram Reels from trend briefs.

    Parameters
    ----------
    persona : Persona
        The AI persona instance (identity, style, tone).
    text_generator
        Any object that exposes ``generate(prompt: str) -> str`` and
        ``generate_caption(topic: str) -> str``.
    image_client
        Any object that exposes ``generate_image(prompt: str) -> bytes``
        and ``save_image(data: bytes, filename: str, output_dir: str) -> str``.
    """

    def __init__(
        self,
        persona: Persona,
        text_generator: Any,
        image_client: Any,
    ) -> None:
        self._persona = persona
        self._text_gen = text_generator
        self._image_client = image_client

    # ------------------------------------------------------------------
    # Content generation
    # ------------------------------------------------------------------

    def create_reel_content(self, brief: dict) -> dict:
        """Generate full reel content based on a trend brief.

        Parameters
        ----------
        brief : dict
            Output of ``TrendDetector.generate_content_brief()``.  Expected
            keys: ``topic``, ``visual_style``, ``music_suggestion``,
            ``caption_style``, ``hashtags``, ``duration``, ``composition``,
            ``color_palette``.

        Returns
        -------
        dict
            ``{"frames": [image_paths], "caption": str, "hashtags": list,
            "audio_suggestion": dict, "duration": float}``
        """
        topic = brief.get("topic", "daily life")
        visual_style = brief.get("visual_style", "")
        duration = brief.get("duration", 15.0)
        composition = brief.get("composition", "medium")
        color_palette = brief.get("color_palette", [])
        caption_style = brief.get("caption_style", {})

        # Determine number of frames (~3 seconds each)
        num_frames = max(2, int(duration / 3))
        logger.info(
            "Generating {} frames for {:.0f}s reel on '{}'",
            num_frames, duration, topic,
        )

        # Generate image frames
        frames: list[str] = []
        _DEFAULT_FRAME_DIR.mkdir(parents=True, exist_ok=True)
        reel_id = uuid.uuid4().hex[:8]

        for i in range(num_frames):
            frame_prompt = self._build_frame_prompt(
                topic=topic,
                visual_style=visual_style,
                composition=composition,
                color_palette=color_palette,
                frame_index=i,
                total_frames=num_frames,
            )

            try:
                image_data = self._image_client.generate_image(frame_prompt)
                filename = f"reel_{reel_id}_frame_{i:02d}.png"
                saved_path = self._image_client.save_image(
                    image_data,
                    filename=filename,
                    output_dir=str(_DEFAULT_FRAME_DIR),
                )
                frames.append(saved_path)
                logger.debug("Frame {}/{} generated: {}", i + 1, num_frames, saved_path)
            except Exception as exc:
                logger.error("Failed to generate frame {}: {}", i, exc)

        if not frames:
            logger.error("No frames generated – cannot create reel content.")
            return {
                "frames": [],
                "caption": "",
                "hashtags": [],
                "audio_suggestion": brief.get("music_suggestion", {}),
                "duration": duration,
            }

        # Generate caption
        caption = self._generate_caption(topic, caption_style)

        # Hashtags
        hashtags = brief.get("hashtags", [])

        result = {
            "frames": frames,
            "caption": caption,
            "hashtags": hashtags,
            "audio_suggestion": brief.get("music_suggestion", {}),
            "duration": duration,
        }

        logger.info(
            "Reel content ready: {} frames, caption length={}, {} hashtags",
            len(frames), len(caption), len(hashtags),
        )
        return result

    # ------------------------------------------------------------------
    # Video composition
    # ------------------------------------------------------------------

    def compose_reel_video(
        self,
        frames: list[str],
        duration: float = 15.0,
        transition: str = "fade",
    ) -> str:
        """Compose a sequence of images into a video with transitions.

        Parameters
        ----------
        frames : list[str]
            Ordered list of image file paths.
        duration : float
            Total video duration in seconds.
        transition : str
            Transition style: ``"fade"``, ``"slide"``, or ``"cut"``.

        Returns
        -------
        str
            Absolute path to the output video file.

        Raises
        ------
        RuntimeError
            If ffmpeg is not available or composition fails.
        """
        if not frames:
            raise ValueError("At least one frame is required to compose a reel.")

        _DEFAULT_REEL_DIR.mkdir(parents=True, exist_ok=True)
        output_name = f"reel_{uuid.uuid4().hex[:8]}.mp4"
        output_path = _DEFAULT_REEL_DIR / output_name

        frame_duration = duration / len(frames)

        ffmpeg = _import_ffmpeg()

        if ffmpeg is not None:
            try:
                result_path = self._compose_with_ffmpeg_python(
                    ffmpeg, frames, frame_duration, transition, output_path,
                )
                return result_path
            except Exception as exc:
                logger.warning(
                    "ffmpeg-python composition failed, falling back to CLI: {}",
                    exc,
                )

        # Fallback: ffmpeg CLI via subprocess
        return self._compose_with_ffmpeg_cli(
            frames, frame_duration, transition, output_path,
        )

    def create_slideshow_reel(
        self,
        image_paths: list[str],
        durations: Optional[list[float]] = None,
        music_path: Optional[str] = None,
    ) -> str:
        """Create a simple slideshow-style reel from images.

        Parameters
        ----------
        image_paths : list[str]
            Ordered list of image file paths.
        durations : list[float] | None
            Per-image durations in seconds.  Defaults to 3 s each.
        music_path : str | None
            Optional path to a music file to mix into the video.

        Returns
        -------
        str
            Absolute path to the output video file.
        """
        if not image_paths:
            raise ValueError("At least one image is required for a slideshow.")

        if durations is None:
            durations = [3.0] * len(image_paths)
        elif len(durations) != len(image_paths):
            logger.warning(
                "Duration list length ({}) != image count ({}). Padding with 3s.",
                len(durations), len(image_paths),
            )
            while len(durations) < len(image_paths):
                durations.append(3.0)

        _DEFAULT_REEL_DIR.mkdir(parents=True, exist_ok=True)
        output_name = f"slideshow_{uuid.uuid4().hex[:8]}.mp4"
        output_path = _DEFAULT_REEL_DIR / output_name

        # Build ffmpeg concat demuxer input file
        concat_path = _DEFAULT_REEL_DIR / f"_concat_{uuid.uuid4().hex[:6]}.txt"
        try:
            lines: list[str] = []
            for img, dur in zip(image_paths, durations):
                abs_img = str(Path(img).resolve())
                lines.append(f"file '{abs_img}'")
                lines.append(f"duration {dur}")
            # Repeat last entry (ffmpeg concat demuxer quirk)
            if image_paths:
                lines.append(f"file '{str(Path(image_paths[-1]).resolve())}'")

            concat_path.write_text("\n".join(lines), encoding="utf-8")

            cmd: list[str] = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_path),
                "-vsync", "vfr",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
                "-pix_fmt", "yuv420p",
            ]

            if music_path and Path(music_path).exists():
                total_dur = sum(durations)
                cmd.extend([
                    "-i", music_path,
                    "-t", str(total_dur),
                    "-shortest",
                    "-c:a", "aac", "-b:a", "128k",
                ])
            else:
                # Silent audio for Instagram compatibility
                total_dur = sum(durations)
                cmd.extend([
                    "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                    "-t", str(total_dur),
                    "-shortest",
                    "-c:a", "aac", "-b:a", "128k",
                ])

            cmd.extend(["-c:v", "libx264", "-preset", "fast", str(output_path)])

            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
            logger.info("Slideshow reel created -> {}", output_path)
            return str(output_path)

        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.error("Slideshow creation failed: {}", exc)
            raise RuntimeError(f"Failed to create slideshow reel: {exc}") from exc
        finally:
            try:
                concat_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Optimal duration
    # ------------------------------------------------------------------

    @staticmethod
    def get_optimal_duration(trend_patterns: dict) -> float:
        """Suggest a reel duration based on trending content patterns.

        Parameters
        ----------
        trend_patterns : dict
            Output of ``TrendDetector.detect_patterns()``.

        Returns
        -------
        float
            Recommended duration in seconds (clamped to 7-90 s).
        """
        visual_trends = trend_patterns.get("visual_trends", [])

        for trend in visual_trends:
            if trend.get("type") == "duration":
                avg = trend.get("average", 15.0)
                # Clamp to Instagram reel limits
                clamped = max(7.0, min(90.0, avg))
                logger.info("Optimal reel duration from trends: {:.1f}s", clamped)
                return clamped

        # Default: 15-second reels tend to perform well
        logger.info("No duration trend data – defaulting to 15.0s")
        return 15.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_frame_prompt(
        self,
        topic: str,
        visual_style: str,
        composition: str,
        color_palette: list[str],
        frame_index: int,
        total_frames: int,
    ) -> str:
        """Build an image-generation prompt for a single reel frame."""
        # Base appearance from persona
        base = ""
        if hasattr(self._persona, "appearance_prompt"):
            base = self._persona.appearance_prompt

        # Scene progression (opening / middle / closing)
        if frame_index == 0:
            scene_hint = "opening scene, establishing shot"
        elif frame_index == total_frames - 1:
            scene_hint = "closing scene, final pose or moment"
        else:
            scene_hint = f"scene {frame_index + 1}, natural continuation"

        color_desc = ""
        if color_palette:
            color_desc = f" Colour palette: {', '.join(color_palette[:3])}."

        prompt = (
            f"{base} "
            f"Topic: {topic}. {scene_hint}. "
            f"Composition: {composition} shot. "
            f"{visual_style}.{color_desc} "
            f"High quality, Instagram reel style, vertical 9:16 aspect ratio."
        )

        return prompt.strip()

    def _generate_caption(self, topic: str, caption_style: dict) -> str:
        """Generate a caption using the text generator.

        Falls back to a simple template if the text generator is unavailable.
        """
        target_length = caption_style.get("target_length", 100)
        tone = caption_style.get("tone", "conversational")
        include_cta = caption_style.get("include_cta", True)
        emoji_count = caption_style.get("emoji_count", 2)

        # Try using generate_caption (higher-level) first
        if hasattr(self._text_gen, "generate_caption"):
            try:
                caption = self._text_gen.generate_caption(topic=topic)
                if caption:
                    return caption
            except Exception as exc:
                logger.warning("generate_caption failed: {}", exc)

        # Fallback: use raw generate with a detailed prompt
        if hasattr(self._text_gen, "generate"):
            try:
                prompt = (
                    f"Write a short Instagram reel caption about '{topic}'.\n"
                    f"Tone: {tone}.\n"
                    f"Target length: ~{target_length} characters.\n"
                    f"Use up to {emoji_count} emojis.\n"
                )
                if include_cta:
                    prompt += "Include a call-to-action or question for followers.\n"

                if hasattr(self._persona, "name"):
                    prompt += f"Write as {self._persona.name}.\n"

                caption = self._text_gen.generate(prompt)
                if caption:
                    return caption
            except Exception as exc:
                logger.warning("Text generation fallback failed: {}", exc)

        # Last resort: template
        logger.warning("Using template caption – text generator unavailable.")
        return f"{topic} ✨"

    @staticmethod
    def _compose_with_ffmpeg_python(
        ffmpeg: Any,
        frames: list[str],
        frame_duration: float,
        transition: str,
        output_path: Path,
    ) -> str:
        """Compose frames into a video using ffmpeg-python."""
        if len(frames) == 1:
            # Single frame: just create a static video
            (
                ffmpeg
                .input(frames[0], loop=1, t=frame_duration)
                .filter("scale", 1080, 1920, force_original_aspect_ratio="decrease")
                .filter("pad", 1080, 1920, "(ow-iw)/2", "(oh-ih)/2")
                .output(
                    str(output_path),
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    preset="fast",
                    t=frame_duration,
                )
                .overwrite_output()
                .run(quiet=True)
            )
            return str(output_path)

        # Multiple frames: use concat with optional crossfade
        inputs = []
        for frame_path in frames:
            inp = (
                ffmpeg
                .input(frame_path, loop=1, t=frame_duration)
                .filter("scale", 1080, 1920, force_original_aspect_ratio="decrease")
                .filter("pad", 1080, 1920, "(ow-iw)/2", "(oh-ih)/2")
                .filter("setsar", 1)
            )
            inputs.append(inp)

        if transition == "fade" and len(inputs) >= 2:
            # Apply crossfade between consecutive clips
            fade_dur = min(0.5, frame_duration / 3)
            merged = inputs[0]
            for i in range(1, len(inputs)):
                offset = frame_duration * i - fade_dur * i
                merged = ffmpeg.filter(
                    [merged, inputs[i]],
                    "xfade",
                    transition="fade",
                    duration=fade_dur,
                    offset=max(0, offset),
                )
            merged.output(
                str(output_path),
                vcodec="libx264",
                pix_fmt="yuv420p",
                preset="fast",
            ).overwrite_output().run(quiet=True)
        else:
            # Simple concat
            joined = ffmpeg.concat(*inputs, v=1, a=0)
            joined.output(
                str(output_path),
                vcodec="libx264",
                pix_fmt="yuv420p",
                preset="fast",
            ).overwrite_output().run(quiet=True)

        logger.info("Reel composed (ffmpeg-python) -> {}", output_path)
        return str(output_path)

    @staticmethod
    def _compose_with_ffmpeg_cli(
        frames: list[str],
        frame_duration: float,
        transition: str,
        output_path: Path,
    ) -> str:
        """Compose frames into a video using the ffmpeg CLI."""
        # Build a concat demuxer input
        concat_path = output_path.with_suffix(".txt")
        try:
            lines: list[str] = []
            for frame_path in frames:
                abs_path = str(Path(frame_path).resolve())
                lines.append(f"file '{abs_path}'")
                lines.append(f"duration {frame_duration}")
            # Repeat last (ffmpeg concat quirk)
            if frames:
                lines.append(f"file '{str(Path(frames[-1]).resolve())}'")

            concat_path.write_text("\n".join(lines), encoding="utf-8")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_path),
                "-vsync", "vfr",
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-preset", "fast",
                str(output_path),
            ]

            subprocess.run(cmd, capture_output=True, timeout=300, check=True)
            logger.info("Reel composed (ffmpeg CLI) -> {}", output_path)
            return str(output_path)

        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise RuntimeError(
                f"ffmpeg CLI reel composition failed: {exc}"
            ) from exc
        finally:
            try:
                concat_path.unlink(missing_ok=True)
            except OSError:
                pass
