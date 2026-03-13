"""
Trending content scraper for Instagram using instagrapi.

Fetches trending reels and posts from the Explore page and by hashtag,
downloads media files, and persists metadata to JSON.  All API calls
include randomised delays (2-5 s) to mimic human browsing patterns.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_RAW_DIR = _PROJECT_ROOT / "data" / "raw"


class TrendScraper:
    """Scrape trending reels and posts from Instagram via *instagrapi*.

    Parameters
    ----------
    client
        An authenticated ``instagrapi.Client`` instance (obtain via
        ``InstagramAuth.get_client()``).
    delay_min : float
        Minimum random delay between API requests (seconds).
    delay_max : float
        Maximum random delay between API requests (seconds).
    """

    def __init__(
        self,
        client: Any,
        delay_min: float = 2.0,
        delay_max: float = 5.0,
    ) -> None:
        self._client = client
        self._delay_min = delay_min
        self._delay_max = delay_max

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _random_delay(self) -> None:
        """Sleep for a random duration between configured bounds."""
        delay = random.uniform(self._delay_min, self._delay_max)
        logger.debug("Rate-limit delay: {:.2f}s", delay)
        time.sleep(delay)

    @staticmethod
    def _media_to_dict(media: Any) -> dict:
        """Convert an instagrapi ``Media`` object to a plain dict.

        Parameters
        ----------
        media
            An ``instagrapi.types.Media`` instance.

        Returns
        -------
        dict
            Normalised metadata dictionary.
        """
        # Audio information (reels / clips)
        audio_name: Optional[str] = None
        audio_id: Optional[str] = None
        if hasattr(media, "clips_metadata") and media.clips_metadata:
            clips = media.clips_metadata
            if hasattr(clips, "music_info") and clips.music_info:
                music = clips.music_info
                audio_name = getattr(music, "song_name", None) or getattr(
                    music, "title", None
                )
                audio_id = str(getattr(music, "audio_id", "")) or None
            elif hasattr(clips, "original_sound_info") and clips.original_sound_info:
                osinfo = clips.original_sound_info
                audio_name = getattr(osinfo, "original_audio_title", None)
                audio_id = str(getattr(osinfo, "audio_id", "")) or None

        # Username
        user: Optional[str] = None
        if hasattr(media, "user") and media.user:
            user = getattr(media.user, "username", None)

        # Thumbnail / video URL
        url: Optional[str] = None
        if hasattr(media, "video_url") and media.video_url:
            url = str(media.video_url)
        elif hasattr(media, "thumbnail_url") and media.thumbnail_url:
            url = str(media.thumbnail_url)

        # Timestamp
        taken_at = getattr(media, "taken_at", None)
        timestamp: Optional[str] = None
        if taken_at is not None:
            if isinstance(taken_at, datetime):
                timestamp = taken_at.isoformat()
            else:
                timestamp = str(taken_at)

        return {
            "media_id": str(media.pk),
            "media_type": str(getattr(media, "media_type", "")),
            "url": url,
            "caption": (media.caption_text if hasattr(media, "caption_text") else ""),
            "likes": getattr(media, "like_count", 0) or 0,
            "views": getattr(media, "view_count", 0) or 0,
            "comments_count": getattr(media, "comment_count", 0) or 0,
            "audio_name": audio_name,
            "audio_id": audio_id,
            "user": user,
            "timestamp": timestamp,
        }

    def _save_metadata(self, items: list[dict], prefix: str = "trending") -> Path:
        """Persist a list of metadata dicts to a timestamped JSON file.

        Parameters
        ----------
        items : list[dict]
            Metadata dictionaries to save.
        prefix : str
            Filename prefix.

        Returns
        -------
        Path
            The written file path.
        """
        _DEFAULT_RAW_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _DEFAULT_RAW_DIR / f"{prefix}_{ts}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
        logger.info("Metadata saved to {}", path)
        return path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_trending_reels(self, count: int = 20) -> list[dict]:
        """Fetch currently trending reels from the Explore / Clips feed.

        Parameters
        ----------
        count : int
            Maximum number of reels to fetch.

        Returns
        -------
        list[dict]
            List of metadata dicts – one per reel.
        """
        logger.info("Fetching up to {} trending reels ...", count)
        results: list[dict] = []

        try:
            self._random_delay()
            medias = self._client.explore_reels(amount=count)
        except Exception as exc:
            logger.error("Failed to fetch explore reels: {}", exc)
            # Fallback: try fetching clips from the reels tab
            try:
                self._random_delay()
                medias = self._client.reels_tray()
                if hasattr(medias, "__iter__"):
                    medias = list(medias)[:count]
                else:
                    medias = []
            except Exception as inner_exc:
                logger.error("Fallback reels fetch also failed: {}", inner_exc)
                medias = []

        for media in medias:
            try:
                results.append(self._media_to_dict(media))
            except Exception as exc:
                logger.warning("Skipping media due to parse error: {}", exc)

        logger.info("Fetched {} trending reels", len(results))
        self._save_metadata(results, prefix="trending_reels")
        return results

    def get_trending_posts(self, count: int = 20) -> list[dict]:
        """Fetch trending posts from the Explore page.

        Parameters
        ----------
        count : int
            Maximum number of posts to fetch.

        Returns
        -------
        list[dict]
            List of metadata dicts – one per post.
        """
        logger.info("Fetching up to {} trending posts ...", count)
        results: list[dict] = []

        try:
            self._random_delay()
            medias = self._client.explore_page(amount=count)
        except Exception as exc:
            logger.error("Failed to fetch explore page: {}", exc)
            medias = []

        for media in medias:
            try:
                results.append(self._media_to_dict(media))
            except Exception as exc:
                logger.warning("Skipping media due to parse error: {}", exc)

        logger.info("Fetched {} trending posts", len(results))
        self._save_metadata(results, prefix="trending_posts")
        return results

    def get_trending_by_hashtag(
        self, hashtag: str, count: int = 20
    ) -> list[dict]:
        """Fetch top/recent posts for a specific hashtag.

        Parameters
        ----------
        hashtag : str
            The hashtag to search (without leading ``#``).
        count : int
            Maximum number of posts to fetch.

        Returns
        -------
        list[dict]
            List of metadata dicts.
        """
        clean_tag = hashtag.lstrip("#")
        logger.info("Fetching up to {} posts for #{} ...", count, clean_tag)
        results: list[dict] = []

        try:
            self._random_delay()
            # Top posts for the hashtag
            medias = self._client.hashtag_medias_top(name=clean_tag, amount=count)
        except Exception as exc:
            logger.error("Failed to fetch hashtag medias: {}", exc)
            # Fallback to recent posts
            try:
                self._random_delay()
                medias = self._client.hashtag_medias_recent(
                    name=clean_tag, amount=count
                )
            except Exception as inner_exc:
                logger.error("Hashtag recent fetch also failed: {}", inner_exc)
                medias = []

        for media in medias:
            try:
                results.append(self._media_to_dict(media))
            except Exception as exc:
                logger.warning("Skipping media due to parse error: {}", exc)

        logger.info("Fetched {} posts for #{}", len(results), clean_tag)
        self._save_metadata(results, prefix=f"hashtag_{clean_tag}")
        return results

    def download_reel(
        self,
        media_id: str,
        output_dir: str = "data/raw/reels",
    ) -> str:
        """Download a reel's video file to disk.

        Parameters
        ----------
        media_id : str
            The Instagram media PK / ID of the reel.
        output_dir : str
            Target directory (relative to project root or absolute).

        Returns
        -------
        str
            Absolute path to the downloaded video file.
        """
        out = Path(output_dir)
        if not out.is_absolute():
            out = _PROJECT_ROOT / out
        out.mkdir(parents=True, exist_ok=True)

        self._random_delay()

        try:
            logger.info("Downloading reel {} ...", media_id)
            path = self._client.clip_download(
                media_pk=int(media_id),
                folder=out,
            )
            result_path = str(path)
            logger.info("Reel downloaded -> {}", result_path)
            return result_path
        except Exception as exc:
            logger.error("Failed to download reel {}: {}", media_id, exc)
            # Fallback: try generic video download
            try:
                path = self._client.video_download(
                    media_pk=int(media_id),
                    folder=out,
                )
                result_path = str(path)
                logger.info("Reel downloaded (fallback) -> {}", result_path)
                return result_path
            except Exception as inner_exc:
                logger.error(
                    "Fallback download also failed for {}: {}",
                    media_id,
                    inner_exc,
                )
                raise

    def download_thumbnail(
        self,
        media_id: str,
        output_dir: str = "data/raw/thumbnails",
    ) -> str:
        """Download the thumbnail image of a post or reel.

        Parameters
        ----------
        media_id : str
            The Instagram media PK / ID.
        output_dir : str
            Target directory (relative to project root or absolute).

        Returns
        -------
        str
            Absolute path to the downloaded thumbnail file.
        """
        out = Path(output_dir)
        if not out.is_absolute():
            out = _PROJECT_ROOT / out
        out.mkdir(parents=True, exist_ok=True)

        self._random_delay()

        try:
            logger.info("Downloading thumbnail for {} ...", media_id)
            path = self._client.photo_download(
                media_pk=int(media_id),
                folder=out,
            )
            result_path = str(path)
            logger.info("Thumbnail downloaded -> {}", result_path)
            return result_path
        except Exception as exc:
            logger.error(
                "Failed to download thumbnail {}: {}", media_id, exc
            )
            raise
