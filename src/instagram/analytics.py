"""
Instagram analytics via the Facebook/Instagram Graph API.

Retrieves media-level and account-level insights such as impressions,
reach, and engagement.  Falls back gracefully when the Graph API is not
configured (i.e., no access token is available).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

from src.utils.error_handler import InstagramError
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _PROJECT_ROOT / "config" / "settings.yaml"
_GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


def _load_settings() -> dict:
    """Load and return the full settings dict."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except (OSError, yaml.YAMLError):
        return {}


class InstagramAnalytics:
    """Fetch insights from the Instagram Graph API.

    Credentials are loaded from environment variables:
    - ``INSTAGRAM_GRAPH_ACCESS_TOKEN`` – long-lived access token
    - ``INSTAGRAM_BUSINESS_ACCOUNT_ID`` – Instagram Business/Creator account ID

    If these variables are not set, every method returns an empty result
    with a warning instead of raising an error ("graceful fallback").

    Parameters
    ----------
    env_path : Path | str | None
        Path to a ``.env`` file.  Defaults to ``<project_root>/.env``.
    """

    def __init__(self, env_path: Optional[Path | str] = None) -> None:
        env_file = Path(env_path) if env_path else _PROJECT_ROOT / ".env"
        load_dotenv(dotenv_path=env_file)

        self._access_token: str = os.getenv("INSTAGRAM_GRAPH_ACCESS_TOKEN", "")
        self._account_id: str = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
        self._configured: bool = bool(self._access_token and self._account_id)

        if not self._configured:
            logger.warning(
                "Instagram Graph API not configured – analytics will return "
                "empty results.  Set INSTAGRAM_GRAPH_ACCESS_TOKEN and "
                "INSTAGRAM_BUSINESS_ACCOUNT_ID in your .env file."
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_configured(self) -> bool:
        """Return True if the API is configured, otherwise log a warning."""
        if not self._configured:
            logger.warning("Graph API not configured – skipping request.")
            return False
        return True

    def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Make a GET request to the Graph API.

        Parameters
        ----------
        endpoint : str
            API endpoint path (appended to the base URL).
        params : dict | None
            Query parameters.

        Returns
        -------
        dict
            Parsed JSON response.

        Raises
        ------
        InstagramError
            If the request fails or the API returns an error.
        """
        import httpx  # lazy import to avoid hard dependency at module load

        url = f"{_GRAPH_API_BASE}/{endpoint}"
        query: dict[str, Any] = {"access_token": self._access_token}
        if params:
            query.update(params)

        try:
            response = httpx.get(url, params=query, timeout=30.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text
            raise InstagramError(
                f"Graph API HTTP error {exc.response.status_code}: {error_body}"
            ) from exc
        except httpx.RequestError as exc:
            raise InstagramError(
                f"Graph API request failed: {exc}"
            ) from exc

        if "error" in data:
            raise InstagramError(
                f"Graph API error: {data['error'].get('message', data['error'])}"
            )

        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_media_insights(self, media_id: str) -> dict[str, Any]:
        """Fetch insights for a specific media post.

        Parameters
        ----------
        media_id : str
            The Instagram media ID (Graph API format).

        Returns
        -------
        dict
            Keys: ``impressions``, ``reach``, ``engagement``,
            ``likes``, ``comments``, ``saved``, ``shares``.
            Returns an empty dict if the API is not configured.
        """
        if not self._ensure_configured():
            return {}

        try:
            data = self._get(
                f"{media_id}/insights",
                params={
                    "metric": "impressions,reach,engagement,saved,shares",
                },
            )

            insights: dict[str, Any] = {}
            for entry in data.get("data", []):
                name = entry.get("name", "")
                values = entry.get("values", [{}])
                insights[name] = values[0].get("value", 0) if values else 0

            # Also fetch basic fields for likes/comments.
            fields_data = self._get(
                media_id,
                params={"fields": "like_count,comments_count"},
            )
            insights["likes"] = fields_data.get("like_count", 0)
            insights["comments"] = fields_data.get("comments_count", 0)

            logger.debug("Media insights for {}: {}", media_id, insights)
            return insights

        except InstagramError as exc:
            logger.error("Failed to get media insights: {}", exc)
            return {}

    def get_account_insights(
        self,
        period: str = "day",
        days: int = 7,
    ) -> dict[str, Any]:
        """Fetch account-level insights over a time range.

        Parameters
        ----------
        period : str
            Aggregation period: ``"day"``, ``"week"``, or ``"days_28"``.
        days : int
            Number of days to look back (max 30).

        Returns
        -------
        dict
            Keys: ``impressions``, ``reach``, ``profile_views``,
            ``follower_count``.  Each value is a list of daily data points.
            Returns an empty dict if the API is not configured.
        """
        if not self._ensure_configured():
            return {}

        since = datetime.utcnow() - timedelta(days=days)
        until = datetime.utcnow()

        try:
            data = self._get(
                f"{self._account_id}/insights",
                params={
                    "metric": "impressions,reach,profile_views,follower_count",
                    "period": period,
                    "since": int(since.timestamp()),
                    "until": int(until.timestamp()),
                },
            )

            insights: dict[str, Any] = {}
            for entry in data.get("data", []):
                name = entry.get("name", "")
                values = entry.get("values", [])
                insights[name] = [
                    {
                        "value": v.get("value", 0),
                        "end_time": v.get("end_time", ""),
                    }
                    for v in values
                ]

            logger.debug("Account insights ({} days): {}", days, insights)
            return insights

        except InstagramError as exc:
            logger.error("Failed to get account insights: {}", exc)
            return {}

    def get_top_posts(self, count: int = 10) -> list[dict[str, Any]]:
        """Retrieve the user's recent media sorted by engagement.

        Parameters
        ----------
        count : int
            Maximum number of posts to return.

        Returns
        -------
        list[dict]
            Each dict contains ``id``, ``timestamp``, ``caption``,
            ``like_count``, ``comments_count``, and ``engagement_score``.
            Returns an empty list if the API is not configured.
        """
        if not self._ensure_configured():
            return []

        try:
            data = self._get(
                f"{self._account_id}/media",
                params={
                    "fields": (
                        "id,timestamp,caption,like_count,comments_count"
                    ),
                    "limit": min(count * 2, 50),  # fetch extra to allow sorting
                },
            )

            posts: list[dict[str, Any]] = []
            for item in data.get("data", []):
                likes = item.get("like_count", 0)
                comments = item.get("comments_count", 0)
                posts.append({
                    "id": item.get("id", ""),
                    "timestamp": item.get("timestamp", ""),
                    "caption": (item.get("caption", "") or "")[:100],
                    "like_count": likes,
                    "comments_count": comments,
                    "engagement_score": likes + comments * 2,
                })

            # Sort by engagement (likes + 2*comments) descending.
            posts.sort(key=lambda p: p["engagement_score"], reverse=True)

            logger.info("Top {} posts retrieved.", min(count, len(posts)))
            return posts[:count]

        except InstagramError as exc:
            logger.error("Failed to get top posts: {}", exc)
            return []
