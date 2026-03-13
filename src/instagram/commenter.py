"""
Instagram comment monitoring and auto-reply module.

Scans recent posts for unreplied comments, generates context-aware
replies using the project's text generator, and posts them while
respecting configurable rate limits.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml
from instagrapi import Client
from instagrapi.exceptions import ClientError

from src.utils.error_handler import (
    InstagramError,
    RateLimitError,
)
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"
_DATA_DIR = _PROJECT_ROOT / "data"
_REPLIED_IDS_FILE = _DATA_DIR / "replied_comment_ids.json"


def _load_instagram_settings() -> dict:
    """Return the ``instagram`` section from settings.yaml."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            settings = yaml.safe_load(fh)
        return settings.get("instagram", {})
    except (OSError, yaml.YAMLError):
        return {}


class TextGenerator(Protocol):
    """Protocol that any text generator must satisfy.

    The ``generate`` method receives a prompt string and returns a
    generated reply string.
    """

    def generate(self, prompt: str) -> str: ...  # pragma: no cover


class CommentMonitor:
    """Monitor and reply to comments on the authenticated user's posts.

    Parameters
    ----------
    client : Client
        An authenticated instagrapi Client.
    text_generator : TextGenerator
        Any object with a ``generate(prompt: str) -> str`` method
        (e.g., the project's inference engine or persona-based generator).
    """

    def __init__(self, client: Client, text_generator: TextGenerator) -> None:
        self._client = client
        self._generator = text_generator

        ig_cfg = _load_instagram_settings()
        rate_limits = ig_cfg.get("rate_limits", {})

        self._comments_per_hour: int = int(rate_limits.get("comments_per_hour", 10))
        self._delay_min: float = float(rate_limits.get("delay_min", 2.0))
        self._delay_max: float = float(rate_limits.get("delay_max", 5.0))

        # Track how many replies have been posted in the current hour window.
        self._reply_count: int = 0
        self._window_start: datetime = datetime.now(tz=timezone.utc)

        # Load already-replied comment IDs from disk.
        self._replied_ids: set[str] = self._load_replied_ids()

    # ------------------------------------------------------------------
    # Replied-ID persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _load_replied_ids() -> set[str]:
        """Load the set of already-replied comment IDs from disk."""
        if not _REPLIED_IDS_FILE.exists():
            return set()
        try:
            data = json.loads(_REPLIED_IDS_FILE.read_text(encoding="utf-8"))
            return set(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load replied IDs: {}", exc)
            return set()

    def _save_replied_ids(self) -> None:
        """Persist the replied comment IDs to disk."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _REPLIED_IDS_FILE.write_text(
            json.dumps(sorted(self._replied_ids), indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> None:
        """Raise if the hourly comment limit has been reached.

        Resets the counter when a new hour window starts.
        """
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self._window_start).total_seconds()

        if elapsed >= 3600:
            # Start a new window.
            self._reply_count = 0
            self._window_start = now

        if self._reply_count >= self._comments_per_hour:
            raise RateLimitError(
                f"Hourly comment limit reached ({self._comments_per_hour}). "
                "Try again later."
            )

    def _random_delay(self) -> None:
        """Sleep for a random duration to mimic human timing."""
        delay = random.uniform(self._delay_min, self._delay_max)
        logger.debug("Comment delay: {:.2f}s", delay)
        time.sleep(delay)

    # ------------------------------------------------------------------
    # Comment retrieval
    # ------------------------------------------------------------------

    def get_recent_comments(
        self,
        media_id: str,
        since_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Fetch comments on a media post from the last *since_hours* hours.

        Parameters
        ----------
        media_id : str
            The media ID to fetch comments for.
        since_hours : int
            Only return comments newer than this many hours.

        Returns
        -------
        list[dict]
            Each dict contains ``id``, ``user_id``, ``username``, ``text``,
            and ``created_at`` keys.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)

        try:
            comments = self._client.media_comments(media_id)
        except ClientError as exc:
            raise InstagramError(
                f"Failed to fetch comments for media {media_id}: {exc}"
            ) from exc

        results: list[dict[str, Any]] = []
        for comment in comments:
            created = comment.created_at_utc
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created and created >= cutoff:
                results.append({
                    "id": str(comment.pk),
                    "user_id": str(comment.user_id),
                    "username": comment.user.username if comment.user else "",
                    "text": comment.text,
                    "created_at": created.isoformat() if created else "",
                })

        logger.debug(
            "Found {} comments on media {} in the last {} hours",
            len(results),
            media_id,
            since_hours,
        )
        return results

    def get_unreplied_comments(
        self,
        media_id: str,
        since_hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Return recent comments that have not yet been replied to.

        Filters out comments from the authenticated user and any comment
        whose ID is already in the replied-IDs set.

        Parameters
        ----------
        media_id : str
            The media ID to check.
        since_hours : int
            Time window in hours.

        Returns
        -------
        list[dict]
            Unreplied comments, same schema as ``get_recent_comments()``.
        """
        all_comments = self.get_recent_comments(media_id, since_hours)

        # Determine the authenticated user's ID to skip own comments.
        try:
            own_user_id = str(self._client.user_id)
        except Exception:  # noqa: BLE001
            own_user_id = ""

        unreplied: list[dict[str, Any]] = []
        for comment in all_comments:
            cid = comment["id"]
            if cid in self._replied_ids:
                continue
            if comment["user_id"] == own_user_id:
                continue
            unreplied.append(comment)

        logger.debug(
            "{} unreplied comments on media {}", len(unreplied), media_id
        )
        return unreplied

    # ------------------------------------------------------------------
    # Replying
    # ------------------------------------------------------------------

    def reply_to_comment(
        self,
        media_id: str,
        comment_id: str,
        text: str,
    ) -> bool:
        """Post a reply to a specific comment.

        Parameters
        ----------
        media_id : str
            The media ID that the comment belongs to.
        comment_id : str
            The comment ID to reply to.
        text : str
            The reply text.

        Returns
        -------
        bool
            ``True`` if the reply was posted successfully.

        Raises
        ------
        RateLimitError
            If the hourly reply limit has been reached.
        InstagramError
            If the reply could not be posted.
        """
        self._check_rate_limit()
        self._random_delay()

        try:
            self._client.media_comment(
                media_id,
                text,
                replied_to_comment_id=int(comment_id),
            )
            self._reply_count += 1
            self._replied_ids.add(comment_id)
            self._save_replied_ids()

            logger.info(
                "Replied to comment {} on media {}: {}",
                comment_id,
                media_id,
                text[:50],
            )
            return True

        except ClientError as exc:
            raise InstagramError(
                f"Failed to reply to comment {comment_id}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Auto-reply orchestration
    # ------------------------------------------------------------------

    def auto_reply_recent(
        self,
        max_replies: int = 5,
        since_hours: int = 24,
    ) -> int:
        """Scan the authenticated user's recent posts and reply to unreplied comments.

        For each unreplied comment the text generator is invoked to craft
        a contextual reply.

        Parameters
        ----------
        max_replies : int
            Maximum number of replies to post in this invocation.
        since_hours : int
            Only consider comments from the last *since_hours* hours.

        Returns
        -------
        int
            The number of replies successfully posted.
        """
        try:
            user_id = self._client.user_id
            recent_medias = self._client.user_medias(user_id, amount=10)
        except ClientError as exc:
            raise InstagramError(
                f"Failed to fetch recent posts: {exc}"
            ) from exc

        total_replied = 0

        for media in recent_medias:
            if total_replied >= max_replies:
                break

            media_id = str(media.id)
            try:
                unreplied = self.get_unreplied_comments(
                    media_id, since_hours=since_hours
                )
            except InstagramError as exc:
                logger.warning("Skipping media {}: {}", media_id, exc)
                continue

            for comment in unreplied:
                if total_replied >= max_replies:
                    break

                try:
                    self._check_rate_limit()
                except RateLimitError:
                    logger.warning("Rate limit hit – stopping auto-reply.")
                    return total_replied

                # Generate a contextual reply.
                prompt = (
                    f"Reply to the following Instagram comment in a friendly, "
                    f"natural tone (1-2 sentences):\n\n"
                    f"\"{comment['text']}\""
                )
                try:
                    reply_text = self._generator.generate(prompt)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Text generation failed for comment {}: {}",
                        comment["id"],
                        exc,
                    )
                    continue

                try:
                    self.reply_to_comment(media_id, comment["id"], reply_text)
                    total_replied += 1
                except (InstagramError, RateLimitError) as exc:
                    logger.warning("Reply failed: {}", exc)
                    continue

        logger.info("Auto-reply complete – {} replies posted.", total_replied)
        return total_replied
