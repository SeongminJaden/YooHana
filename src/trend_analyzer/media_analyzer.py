"""
Deep media analysis for trending Instagram content.

Extracts visual features, audio characteristics, and caption patterns
from downloaded reels and posts.  Heavy dependencies (cv2, librosa,
whisper, ffmpeg) are imported lazily so the module loads even when they
are not installed.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Lazy dependency helpers
# ---------------------------------------------------------------------------


def _import_cv2() -> Any:
    """Import OpenCV lazily, returning ``None`` on failure."""
    try:
        import cv2  # type: ignore[import-untyped]
        return cv2
    except ImportError:
        logger.warning(
            "opencv-python (cv2) is not installed – video/image analysis "
            "features will be unavailable."
        )
        return None


def _import_librosa() -> Any:
    """Import librosa lazily, returning ``None`` on failure."""
    try:
        import librosa  # type: ignore[import-untyped]
        return librosa
    except ImportError:
        logger.warning(
            "librosa is not installed – music tempo/energy analysis "
            "features will be unavailable."
        )
        return None


def _import_whisper() -> Any:
    """Import openai-whisper lazily, returning ``None`` on failure."""
    try:
        import whisper  # type: ignore[import-untyped]
        return whisper
    except ImportError:
        logger.warning(
            "openai-whisper is not installed – speech transcription "
            "will be unavailable."
        )
        return None


def _import_ffmpeg() -> Any:
    """Import ffmpeg-python lazily, returning ``None`` on failure."""
    try:
        import ffmpeg  # type: ignore[import-untyped]
        return ffmpeg
    except ImportError:
        logger.warning(
            "ffmpeg-python is not installed – audio extraction "
            "will be unavailable."
        )
        return None


def _import_numpy() -> Any:
    """Import numpy lazily, returning ``None`` on failure."""
    try:
        import numpy as np  # type: ignore[import-untyped]
        return np
    except ImportError:
        logger.warning("numpy is not installed – some analysis features will be unavailable.")
        return None


# ---------------------------------------------------------------------------
# MediaAnalyzer
# ---------------------------------------------------------------------------


class MediaAnalyzer:
    """Analyse video, audio, image, and caption content from Instagram media.

    All heavy dependencies are loaded lazily on first use.  Methods that
    require a missing dependency log a warning and return a safe default
    rather than raising.

    Parameters
    ----------
    whisper_model : str
        Whisper model size to load for transcription (e.g. ``"base"``,
        ``"small"``, ``"medium"``).
    """

    def __init__(self, whisper_model: str = "base") -> None:
        self._whisper_model_name = whisper_model
        self._whisper_model: Any = None  # loaded on first transcription call

    # ------------------------------------------------------------------
    # Video analysis
    # ------------------------------------------------------------------

    def analyze_video(self, video_path: str) -> dict:
        """Perform full visual analysis of a video file.

        Extracts key frames (one every 2 seconds), detects dominant
        colours, scene composition, text overlays, and transitions.

        Parameters
        ----------
        video_path : str
            Path to the video file.

        Returns
        -------
        dict
            ``{"duration", "fps", "resolution", "key_frames", "scene_types",
            "dominant_colors", "has_text_overlay", "composition",
            "transition_style"}``
        """
        cv2 = _import_cv2()
        np = _import_numpy()

        result: dict[str, Any] = {
            "duration": 0.0,
            "fps": 0.0,
            "resolution": (0, 0),
            "key_frames": [],
            "scene_types": [],
            "dominant_colors": [],
            "has_text_overlay": False,
            "composition": "unknown",
            "transition_style": "cut",
        }

        if cv2 is None or np is None:
            logger.warning("Skipping video analysis – cv2/numpy not available.")
            return result

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("Cannot open video: {}", video_path)
            return result

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0.0

        result["duration"] = round(duration, 2)
        result["fps"] = round(fps, 2)
        result["resolution"] = (width, height)

        # Extract key frames every 2 seconds
        interval_frames = int(fps * 2)
        key_frames: list[dict] = []
        all_colors: list[str] = []
        has_text = False
        compositions: list[str] = []
        prev_hist: Optional[Any] = None
        transition_diffs: list[float] = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % interval_frames == 0:
                timestamp_sec = round(frame_idx / fps, 2)

                # Dominant colours
                colors = self._extract_dominant_colors(frame, cv2, np)
                all_colors.extend(colors)

                # Composition / framing
                comp = self._detect_composition(frame, cv2, height, width)
                compositions.append(comp)

                # Face detection (scene type hint)
                scene_type = self._detect_scene_type(frame, cv2)

                # Text overlay detection
                if self._detect_text_overlay(frame, cv2, np):
                    has_text = True

                # Transition detection via histogram comparison
                hist = cv2.calcHist(
                    [frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256]
                )
                hist = cv2.normalize(hist, hist).flatten()
                if prev_hist is not None:
                    diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    transition_diffs.append(diff)
                prev_hist = hist

                key_frames.append(
                    {
                        "timestamp": timestamp_sec,
                        "dominant_colors": colors,
                        "composition": comp,
                        "scene_type": scene_type,
                    }
                )

            frame_idx += 1

        cap.release()

        result["key_frames"] = key_frames
        result["scene_types"] = list(
            {kf["scene_type"] for kf in key_frames}
        )

        # Aggregate dominant colours
        color_counter = Counter(all_colors)
        result["dominant_colors"] = [c for c, _ in color_counter.most_common(5)]

        result["has_text_overlay"] = has_text

        # Most common composition
        if compositions:
            result["composition"] = Counter(compositions).most_common(1)[0][0]

        # Transition style
        if transition_diffs:
            avg_diff = sum(transition_diffs) / len(transition_diffs)
            if avg_diff > 0.85:
                result["transition_style"] = "smooth"
            elif avg_diff > 0.5:
                result["transition_style"] = "fade"
            else:
                result["transition_style"] = "cut"

        logger.info(
            "Video analysis complete: {:.1f}s, {}x{}, {} key frames",
            duration, width, height, len(key_frames),
        )
        return result

    # ------------------------------------------------------------------
    # Audio analysis
    # ------------------------------------------------------------------

    def analyze_audio(self, video_path: str) -> dict:
        """Extract and analyse the audio track from a video.

        Detects speech vs. music, transcribes speech (if present), and
        estimates music tempo / energy level.

        Parameters
        ----------
        video_path : str
            Path to the video file.

        Returns
        -------
        dict
            ``{"has_voice", "has_music", "transcript", "music_tempo",
            "music_energy", "audio_duration"}``
        """
        result: dict[str, Any] = {
            "has_voice": False,
            "has_music": False,
            "transcript": None,
            "music_tempo": None,
            "music_energy": "unknown",
            "audio_duration": 0.0,
        }

        # Extract audio to a temp WAV
        audio_path = self._extract_audio(video_path)
        if audio_path is None:
            logger.warning("Could not extract audio from {}", video_path)
            return result

        try:
            librosa = _import_librosa()
            np = _import_numpy()

            if librosa is not None and np is not None:
                y, sr = librosa.load(audio_path, sr=None)
                result["audio_duration"] = round(float(len(y) / sr), 2)

                # Speech detection: check RMS energy variance across segments
                rms = librosa.feature.rms(y=y)[0]
                rms_std = float(np.std(rms))
                rms_mean = float(np.mean(rms))

                # Spectral flatness: higher = more noise-like (music tends to be lower)
                flatness = librosa.feature.spectral_flatness(y=y)[0]
                avg_flatness = float(np.mean(flatness))

                # Heuristics for voice vs music
                if rms_mean > 0.01:
                    result["has_music"] = True

                if rms_std > 0.02 and avg_flatness > 0.05:
                    result["has_voice"] = True

                # Tempo detection
                try:
                    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                    tempo_val = float(tempo) if not hasattr(tempo, "__len__") else float(tempo[0])
                    result["music_tempo"] = round(tempo_val, 1)
                except Exception as exc:
                    logger.debug("Tempo detection failed: {}", exc)

                # Energy classification
                if rms_mean > 0.08:
                    result["music_energy"] = "high"
                elif rms_mean > 0.03:
                    result["music_energy"] = "medium"
                elif rms_mean > 0.005:
                    result["music_energy"] = "low"
                else:
                    result["music_energy"] = "silent"

            # Transcription with Whisper
            if result.get("has_voice", False) or librosa is None:
                transcript = self._transcribe(audio_path)
                if transcript:
                    result["has_voice"] = True
                    result["transcript"] = transcript

        finally:
            # Clean up temp audio file
            try:
                Path(audio_path).unlink(missing_ok=True)
            except OSError:
                pass

        logger.info(
            "Audio analysis complete: voice={}, music={}, tempo={}, energy={}",
            result["has_voice"],
            result["has_music"],
            result["music_tempo"],
            result["music_energy"],
        )
        return result

    # ------------------------------------------------------------------
    # Thumbnail / image analysis
    # ------------------------------------------------------------------

    def analyze_thumbnail(self, image_path: str) -> dict:
        """Analyse a thumbnail or post image.

        Parameters
        ----------
        image_path : str
            Path to the image file.

        Returns
        -------
        dict
            ``{"width", "height", "dominant_colors", "brightness",
            "composition", "has_faces", "face_count"}``
        """
        cv2 = _import_cv2()
        np = _import_numpy()

        result: dict[str, Any] = {
            "width": 0,
            "height": 0,
            "dominant_colors": [],
            "brightness": "unknown",
            "composition": "unknown",
            "has_faces": False,
            "face_count": 0,
        }

        if cv2 is None or np is None:
            logger.warning("Skipping thumbnail analysis – cv2/numpy not available.")
            return result

        img = cv2.imread(image_path)
        if img is None:
            logger.error("Cannot read image: {}", image_path)
            return result

        h, w = img.shape[:2]
        result["width"] = w
        result["height"] = h

        # Dominant colours
        result["dominant_colors"] = self._extract_dominant_colors(img, cv2, np)

        # Brightness
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(np.mean(gray))
        if mean_brightness > 170:
            result["brightness"] = "bright"
        elif mean_brightness > 100:
            result["brightness"] = "moderate"
        else:
            result["brightness"] = "dark"

        # Composition
        result["composition"] = self._detect_composition(img, cv2, h, w)

        # Face detection
        face_count = self._count_faces(img, cv2)
        result["has_faces"] = face_count > 0
        result["face_count"] = face_count

        logger.info(
            "Thumbnail analysis complete: {}x{}, brightness={}, faces={}",
            w, h, result["brightness"], face_count,
        )
        return result

    # ------------------------------------------------------------------
    # Caption style analysis
    # ------------------------------------------------------------------

    def analyze_caption_style(self, caption: str) -> dict:
        """Analyse stylistic patterns in a caption string.

        Parameters
        ----------
        caption : str
            The Instagram caption text.

        Returns
        -------
        dict
            ``{"length", "word_count", "emoji_count", "hashtag_count",
            "has_cta", "tone", "line_count", "avg_word_length"}``
        """
        if not caption:
            return {
                "length": 0,
                "word_count": 0,
                "emoji_count": 0,
                "hashtag_count": 0,
                "has_cta": False,
                "tone": "neutral",
                "line_count": 0,
                "avg_word_length": 0.0,
            }

        # Basic metrics
        length = len(caption)
        words = caption.split()
        word_count = len(words)
        line_count = caption.count("\n") + 1

        # Emoji detection (Unicode emoji ranges)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"  # supplemental symbols
            "\U0001FA00-\U0001FA6F"
            "\U0001FA70-\U0001FAFF"
            "\u200D"  # zero-width joiner
            "\u2640-\u2642"
            "\uFE0F"  # variation selector
            "]+",
            flags=re.UNICODE,
        )
        emoji_count = len(emoji_pattern.findall(caption))

        # Hashtags
        hashtag_count = len(re.findall(r"#\w+", caption))

        # Call-to-action detection
        cta_patterns = [
            r"댓글",
            r"알려줘",
            r"추천",
            r"어때",
            r"어떠",
            r"궁금",
            r"공유",
            r"저장",
            r"팔로우",
            r"DM",
            r"link in bio",
            r"check out",
            r"comment",
            r"share",
            r"save",
            r"follow",
            r"tag",
            r"\?",
            r"！",
        ]
        has_cta = any(re.search(p, caption, re.IGNORECASE) for p in cta_patterns)

        # Tone classification (simple heuristic)
        tone = "neutral"
        exclamation_count = caption.count("!") + caption.count("！")
        question_count = caption.count("?") + caption.count("？")

        if exclamation_count >= 2 and emoji_count >= 3:
            tone = "enthusiastic"
        elif question_count >= 1 and has_cta:
            tone = "engaging"
        elif emoji_count >= 2:
            tone = "playful"
        elif length < 50:
            tone = "minimal"
        elif exclamation_count >= 1:
            tone = "upbeat"
        else:
            tone = "conversational"

        # Average word length
        avg_word_length = 0.0
        if word_count > 0:
            total_chars = sum(len(w) for w in words)
            avg_word_length = round(total_chars / word_count, 1)

        result = {
            "length": length,
            "word_count": word_count,
            "emoji_count": emoji_count,
            "hashtag_count": hashtag_count,
            "has_cta": has_cta,
            "tone": tone,
            "line_count": line_count,
            "avg_word_length": avg_word_length,
        }

        logger.debug(
            "Caption analysis: {} chars, {} emojis, tone={}", length, emoji_count, tone
        )
        return result

    # ------------------------------------------------------------------
    # Combined analysis
    # ------------------------------------------------------------------

    def full_analysis(self, video_path: str, caption: str = "") -> dict:
        """Run video, audio, and caption analyses and merge the results.

        Parameters
        ----------
        video_path : str
            Path to the video file.
        caption : str
            Optional caption text for style analysis.

        Returns
        -------
        dict
            Combined dict with keys ``"video"``, ``"audio"``, ``"caption"``.
        """
        logger.info("Running full media analysis on {} ...", video_path)

        video_result = self.analyze_video(video_path)
        audio_result = self.analyze_audio(video_path)
        caption_result = self.analyze_caption_style(caption)

        combined = {
            "video": video_result,
            "audio": audio_result,
            "caption": caption_result,
            "source_path": video_path,
        }

        logger.info("Full analysis complete for {}", video_path)
        return combined

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_dominant_colors(
        frame: Any, cv2: Any, np: Any, k: int = 3
    ) -> list[str]:
        """Extract *k* dominant colours from a BGR frame using k-means.

        Returns colour names (approximate) for the top clusters.
        """
        # Resize for speed
        small = cv2.resize(frame, (64, 64))
        pixels = small.reshape(-1, 3).astype(np.float32)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        try:
            _, labels, centers = cv2.kmeans(
                pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
            )
        except cv2.error:
            return ["unknown"]

        # Convert BGR centres to approximate colour names
        color_names: list[str] = []
        for center in centers:
            b, g, r = int(center[0]), int(center[1]), int(center[2])
            name = _bgr_to_color_name(r, g, b)
            color_names.append(name)

        return color_names

    @staticmethod
    def _detect_composition(
        frame: Any, cv2: Any, height: int, width: int
    ) -> str:
        """Classify frame composition as close-up, medium, or wide shot."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Use face detection as a proxy for framing
        cascade_paths = [
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml",
        ]

        for cascade_path in cascade_paths:
            try:
                face_cascade = cv2.CascadeClassifier(cascade_path)
                faces = face_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30)
                )
                if len(faces) > 0:
                    # Largest face
                    largest = max(faces, key=lambda f: f[2] * f[3])
                    face_area = largest[2] * largest[3]
                    frame_area = width * height
                    ratio = face_area / frame_area if frame_area > 0 else 0

                    if ratio > 0.15:
                        return "close-up"
                    elif ratio > 0.03:
                        return "medium"
                    else:
                        return "wide"
            except Exception:
                continue

        return "wide"

    @staticmethod
    def _detect_scene_type(frame: Any, cv2: Any) -> str:
        """Infer a rough scene type from colour distribution."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)

        avg_s = float(s.mean())
        avg_v = float(v.mean())

        if avg_v < 60:
            return "dark/indoor"
        elif avg_s < 40 and avg_v > 180:
            return "bright/overexposed"
        elif avg_s > 100 and avg_v > 120:
            return "vibrant/outdoor"
        elif avg_s < 60:
            return "muted/indoor"
        else:
            return "natural"

    @staticmethod
    def _detect_text_overlay(frame: Any, cv2: Any, np: Any) -> bool:
        """Detect whether the frame likely contains text overlays.

        Uses edge detection density in the centre region as a proxy.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Focus on the centre and bottom (common text overlay areas)
        roi = gray[h // 3 :, w // 4 : 3 * w // 4]

        edges = cv2.Canny(roi, 50, 150)
        edge_density = float(np.sum(edges > 0)) / edges.size

        # Text overlays tend to produce higher edge density
        return edge_density > 0.15

    @staticmethod
    def _count_faces(frame: Any, cv2: Any) -> int:
        """Count the number of faces in a frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        try:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            return len(faces)
        except Exception:
            return 0

    @staticmethod
    def _extract_audio(video_path: str) -> Optional[str]:
        """Extract the audio track from *video_path* to a temp WAV file.

        Uses ffmpeg CLI as a subprocess (more reliable than ffmpeg-python
        for simple extraction).  Falls back to ffmpeg-python if the CLI
        is unavailable.
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        out_path = tmp.name

        # Try subprocess ffmpeg first (most portable)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    out_path,
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
            return out_path
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logger.debug("ffmpeg CLI extraction failed: {}", exc)

        # Fallback: ffmpeg-python
        ffmpeg = _import_ffmpeg()
        if ffmpeg is not None:
            try:
                (
                    ffmpeg
                    .input(video_path)
                    .output(out_path, acodec="pcm_s16le", ar=16000, ac=1)
                    .overwrite_output()
                    .run(quiet=True)
                )
                return out_path
            except Exception as exc:
                logger.debug("ffmpeg-python extraction failed: {}", exc)

        # Clean up on failure
        try:
            Path(out_path).unlink(missing_ok=True)
        except OSError:
            pass
        return None

    def _transcribe(self, audio_path: str) -> Optional[str]:
        """Transcribe speech from an audio file using Whisper.

        Returns the transcript string, or *None* if Whisper is unavailable
        or transcription fails.
        """
        whisper = _import_whisper()
        if whisper is None:
            return None

        try:
            if self._whisper_model is None:
                logger.info(
                    "Loading Whisper model '{}' ...", self._whisper_model_name
                )
                self._whisper_model = whisper.load_model(self._whisper_model_name)

            result = self._whisper_model.transcribe(audio_path)
            text = result.get("text", "").strip()
            if text:
                logger.debug("Transcription ({} chars): {}...", len(text), text[:80])
                return text
            return None
        except Exception as exc:
            logger.warning("Whisper transcription failed: {}", exc)
            return None


# ---------------------------------------------------------------------------
# Colour name helper
# ---------------------------------------------------------------------------


def _bgr_to_color_name(r: int, g: int, b: int) -> str:
    """Map an RGB triple to an approximate colour name."""
    colour_map = [
        ("white", (255, 255, 255)),
        ("black", (0, 0, 0)),
        ("red", (255, 0, 0)),
        ("green", (0, 128, 0)),
        ("blue", (0, 0, 255)),
        ("yellow", (255, 255, 0)),
        ("orange", (255, 165, 0)),
        ("purple", (128, 0, 128)),
        ("pink", (255, 192, 203)),
        ("brown", (139, 69, 19)),
        ("gray", (128, 128, 128)),
        ("beige", (245, 245, 220)),
        ("navy", (0, 0, 128)),
        ("teal", (0, 128, 128)),
        ("coral", (255, 127, 80)),
    ]

    min_dist = float("inf")
    best_name = "unknown"
    for name, (cr, cg, cb) in colour_map:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < min_dist:
            min_dist = dist
            best_name = name

    return best_name
