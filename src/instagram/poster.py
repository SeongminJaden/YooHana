"""
Instagram content posting module using instagrapi.

Supports photo, story, and carousel uploads with rate-limiting delays
to avoid triggering Instagram's anti-automation systems.
"""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Optional

import yaml
from instagrapi import Client
from instagrapi.exceptions import ClientError

from src.utils.error_handler import InstagramError
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"


def _load_delay_settings() -> tuple[float, float]:
    """Load delay_min/delay_max from settings.yaml."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            settings = yaml.safe_load(fh)
        rate_limits = settings.get("instagram", {}).get("rate_limits", {})
        return (
            float(rate_limits.get("delay_min", 2.0)),
            float(rate_limits.get("delay_max", 5.0)),
        )
    except (OSError, yaml.YAMLError):
        return (2.0, 5.0)


class InstagramPoster:
    """Upload photos, stories, and carousels to Instagram.

    Parameters
    ----------
    client : Client
        An authenticated instagrapi Client (obtain via ``InstagramAuth.get_client()``).
    """

    def __init__(self, client: Client) -> None:
        self._client = client
        self._delay_min, self._delay_max = _load_delay_settings()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _random_delay(self) -> None:
        """Sleep for a random duration between configured min/max seconds."""
        delay = random.uniform(self._delay_min, self._delay_max)
        logger.debug("Rate-limit delay: {:.2f}s", delay)
        time.sleep(delay)

    @staticmethod
    def _build_caption(caption: str, hashtags: Optional[list[str]] = None) -> str:
        """Append hashtags to a caption string.

        Parameters
        ----------
        caption : str
            The main caption text.
        hashtags : list[str] | None
            Optional hashtags to append (with or without leading ``#``).

        Returns
        -------
        str
            The full caption with hashtags on a new line.
        """
        if not hashtags:
            return caption

        normalised = [
            tag if tag.startswith("#") else f"#{tag}" for tag in hashtags
        ]
        tag_line = " ".join(normalised)
        return f"{caption}\n\n{tag_line}"

    @staticmethod
    def _validate_image(image_path: str) -> Path:
        """Ensure the image file exists and return a Path object."""
        path = Path(image_path)
        if not path.exists():
            raise InstagramError(f"Image file not found: {path}")
        if not path.is_file():
            raise InstagramError(f"Not a file: {path}")
        return path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post_photo(
        self,
        image_path: str,
        caption: str,
        hashtags: Optional[list[str]] = None,
    ) -> str:
        """Upload a single photo with a caption.

        Parameters
        ----------
        image_path : str
            Path to the image file.
        caption : str
            Caption text.
        hashtags : list[str] | None
            Optional hashtags to append.

        Returns
        -------
        str
            The media ID of the published post.

        Raises
        ------
        InstagramError
            If the upload fails.
        """
        path = self._validate_image(image_path)
        full_caption = self._build_caption(caption, hashtags)

        self._random_delay()

        try:
            media = self._client.photo_upload(
                path=path,
                caption=full_caption,
            )
            media_id = str(media.id)
            logger.info("Photo posted successfully – media_id={}", media_id)
            return media_id

        except ClientError as exc:
            raise InstagramError(f"Photo upload failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise InstagramError(
                f"Unexpected error during photo upload: {exc}"
            ) from exc

    def post_story(
        self,
        image_path: str,
        caption: Optional[str] = None,
    ) -> str:
        """Upload an image as an Instagram story.

        Parameters
        ----------
        image_path : str
            Path to the image file.
        caption : str | None
            Optional caption/sticker text for the story.

        Returns
        -------
        str
            The media ID of the published story.

        Raises
        ------
        InstagramError
            If the upload fails.
        """
        path = self._validate_image(image_path)

        self._random_delay()

        try:
            media = self._client.photo_upload_to_story(
                path=path,
                caption=caption or "",
            )
            media_id = str(media.id)
            logger.info("Story posted successfully – media_id={}", media_id)
            return media_id

        except ClientError as exc:
            raise InstagramError(f"Story upload failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise InstagramError(
                f"Unexpected error during story upload: {exc}"
            ) from exc

    def post_carousel(
        self,
        image_paths: list[str],
        caption: str,
        hashtags: Optional[list[str]] = None,
    ) -> str:
        """Upload multiple images as a carousel (album) post.

        Parameters
        ----------
        image_paths : list[str]
            Paths to the image files (minimum 2).
        caption : str
            Caption text.
        hashtags : list[str] | None
            Optional hashtags to append.

        Returns
        -------
        str
            The media ID of the published carousel.

        Raises
        ------
        InstagramError
            If fewer than 2 images are provided or the upload fails.
        """
        if len(image_paths) < 2:
            raise InstagramError(
                "Carousel requires at least 2 images, "
                f"got {len(image_paths)}."
            )

        paths = [self._validate_image(p) for p in image_paths]
        full_caption = self._build_caption(caption, hashtags)

        self._random_delay()

        try:
            media = self._client.album_upload(
                paths=paths,
                caption=full_caption,
            )
            media_id = str(media.id)
            logger.info(
                "Carousel posted successfully ({} images) – media_id={}",
                len(paths),
                media_id,
            )
            return media_id

        except ClientError as exc:
            raise InstagramError(
                f"Carousel upload failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise InstagramError(
                f"Unexpected error during carousel upload: {exc}"
            ) from exc

    def post_reel(
        self,
        video_path: str,
        caption: str,
        hashtags: Optional[list[str]] = None,
        thumbnail_path: Optional[str] = None,
    ) -> str:
        """Upload a video as an Instagram Reel.

        Parameters
        ----------
        video_path : str
            Path to the video file (MP4, 9:16 aspect ratio recommended).
        caption : str
            Caption text.
        hashtags : list[str] | None
            Optional hashtags to append.
        thumbnail_path : str | None
            Optional custom thumbnail image.

        Returns
        -------
        str
            The media ID of the published reel.

        Raises
        ------
        InstagramError
            If the upload fails.
        """
        path = Path(video_path)
        if not path.exists():
            raise InstagramError(f"Video file not found: {path}")

        full_caption = self._build_caption(caption, hashtags)

        self._random_delay()

        try:
            kwargs = {"path": path, "caption": full_caption}
            if thumbnail_path:
                thumb = Path(thumbnail_path)
                if thumb.exists():
                    kwargs["thumbnail"] = thumb

            media = self._client.clip_upload(**kwargs)
            media_id = str(media.id)
            logger.info("Reel posted successfully – media_id={}", media_id)
            return media_id

        except ClientError as exc:
            raise InstagramError(f"Reel upload failed: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise InstagramError(
                f"Unexpected error during reel upload: {exc}"
            ) from exc
