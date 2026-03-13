"""
Instagram comprehensive crawler using instagrapi.

Collects posts, reels, captions, comments, and engagement data
from public accounts, hashtags, and explore/search results.
"""
from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    LoginRequired,
    PrivateError,
    UserNotFound,
)

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_DATA_DIR = _PROJECT_ROOT / "data" / "raw"
_SESSION_FILE = _PROJECT_ROOT / "instagram_session.json"


class InstagramCrawler:
    """Comprehensive Instagram data crawler.

    Logs in once, saves session for reuse, and provides methods to
    crawl posts, reels, comments, and search results.
    """

    def __init__(self, delay_range: tuple[float, float] = (3.0, 6.0)) -> None:
        self.client = Client()
        self.client.delay_range = [1, 3]
        self.delay_range = delay_range
        self._logged_in = False
        self._all_collected: list[dict] = []

        # Load credentials from .env
        from dotenv import load_dotenv
        load_dotenv(_PROJECT_ROOT / ".env")

        username = os.getenv("INSTAGRAM_USERNAME", "")
        password = os.getenv("INSTAGRAM_PASSWORD", "")

        if username and password:
            self._login(username, password)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _login(self, username: str, password: str) -> None:
        """Login with session reuse."""
        # Try loading saved session first
        if _SESSION_FILE.exists():
            try:
                self.client.load_settings(str(_SESSION_FILE))
                self.client.login(username, password)
                self.client.get_timeline_feed()  # Verify session is valid
                self._logged_in = True
                logger.info("Logged in via saved session as {}", username)
                return
            except Exception:
                logger.info("Saved session expired, doing fresh login...")
                _SESSION_FILE.unlink(missing_ok=True)

        # Fresh login with challenge handling
        try:
            self.client.login(username, password)
            self.client.dump_settings(str(_SESSION_FILE))
            self._logged_in = True
            logger.info("Fresh login successful as {}", username)
        except ChallengeRequired:
            logger.info("Challenge required - attempting to resolve...")
            try:
                # Try to auto-resolve challenge
                self.client.challenge_resolve(self.client.last_json)
                self.client.dump_settings(str(_SESSION_FILE))
                self._logged_in = True
                logger.info("Challenge resolved successfully")
            except Exception:
                logger.warning("Auto-resolve failed. Waiting 30s for manual approval...")
                import time
                time.sleep(30)
                # Retry login after manual approval
                try:
                    self.client = Client()
                    self.client.login(username, password)
                    self.client.dump_settings(str(_SESSION_FILE))
                    self._logged_in = True
                    logger.info("Login successful after manual approval")
                except Exception as exc2:
                    logger.error("Login still failing after approval: {}", exc2)
                    raise
        except Exception as exc:
            logger.error("Login failed: {}", exc)
            raise

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _delay(self) -> None:
        delay = random.uniform(*self.delay_range)
        time.sleep(delay)

    # ------------------------------------------------------------------
    # Core data extraction
    # ------------------------------------------------------------------

    def _media_to_dict(self, media: Any, source: str = "") -> dict[str, Any]:
        """Extract all useful data from a Media object."""
        media_type = "reel" if media.media_type == 2 and media.product_type == "clips" else \
                     "video" if media.media_type == 2 else \
                     "carousel" if media.media_type == 8 else "photo"

        data = {
            "media_id": str(media.pk),
            "media_type": media_type,
            "caption": media.caption_text or "",
            "likes": media.like_count or 0,
            "comments_count": media.comment_count or 0,
            "views": getattr(media, "view_count", 0) or 0,
            "play_count": getattr(media, "play_count", 0) or 0,
            "timestamp": media.taken_at.isoformat() if media.taken_at else "",
            "user": media.user.username if media.user else "",
            "user_followers": 0,  # filled separately if needed
            "source": source,
            "thumbnail_url": str(media.thumbnail_url) if media.thumbnail_url else "",
            "video_url": str(media.video_url) if getattr(media, "video_url", None) else "",
            "hashtags": self._extract_hashtags(media.caption_text or ""),
            "mentions": self._extract_mentions(media.caption_text or ""),
        }

        # Audio info for reels
        if hasattr(media, "clips_metadata") and media.clips_metadata:
            clips = media.clips_metadata
            if hasattr(clips, "music_info") and clips.music_info:
                music = clips.music_info
                data["audio_name"] = getattr(music, "music_asset_info", {})
            elif hasattr(clips, "original_sound_info") and clips.original_sound_info:
                data["audio_name"] = "original_sound"

        return data

    @staticmethod
    def _extract_hashtags(text: str) -> list[str]:
        import re
        return re.findall(r"#(\w+)", text)

    @staticmethod
    def _extract_mentions(text: str) -> list[str]:
        import re
        return re.findall(r"@(\w+)", text)

    # ------------------------------------------------------------------
    # Comment collection
    # ------------------------------------------------------------------

    def collect_comments(self, media_id: str, count: int = 20) -> list[dict]:
        """Collect comments from a specific post/reel."""
        try:
            comments = self.client.media_comments(media_id, amount=count)
            self._delay()
        except Exception as exc:
            logger.warning("Failed to get comments for {}: {}", media_id, exc)
            return []

        results = []
        for c in comments:
            comment_data = {
                "comment_id": str(c.pk),
                "media_id": media_id,
                "text": c.text or "",
                "user": c.user.username if c.user else "",
                "likes": getattr(c, "like_count", 0) or 0,
                "timestamp": c.created_at_utc.isoformat() if c.created_at_utc else "",
            }
            if comment_data["text"]:
                results.append(comment_data)

        return results

    # ------------------------------------------------------------------
    # User posts/reels collection
    # ------------------------------------------------------------------

    def crawl_user(
        self,
        username: str,
        max_posts: int = 50,
        include_comments: bool = True,
        comments_per_post: int = 10,
    ) -> list[dict]:
        """Crawl all posts and reels from a user account."""
        logger.info("=== Crawling @{} (max {} posts) ===", username, max_posts)

        try:
            user_id = self.client.user_id_from_username(username)
            self._delay()
        except UserNotFound:
            logger.error("User @{} not found", username)
            return []
        except Exception as exc:
            logger.error("Failed to resolve @{}: {}", username, exc)
            return []

        # Check private
        try:
            info = self.client.user_info(user_id)
            if info.is_private:
                logger.warning("@{} is private - skipping", username)
                return []
            logger.info("@{}: {} followers, {} posts", username, info.follower_count, info.media_count)
            self._delay()
        except Exception as exc:
            logger.warning("Can't check @{} info: {}", username, exc)
            return []

        # Fetch all medias (posts + reels)
        results = []
        try:
            medias = self.client.user_medias(user_id, amount=max_posts)
            logger.info("Fetched {} medias from @{}", len(medias), username)
        except Exception as exc:
            logger.error("Failed to fetch medias from @{}: {}", username, exc)
            return []

        for i, media in enumerate(medias):
            record = self._media_to_dict(media, source=f"@{username}")
            record["user_followers"] = info.follower_count or 0

            # Collect comments
            if include_comments and record["comments_count"] > 0:
                record["comments"] = self.collect_comments(
                    record["media_id"], count=comments_per_post
                )
            else:
                record["comments"] = []

            results.append(record)
            self._delay()

            if (i + 1) % 10 == 0:
                logger.info("  Progress: {}/{} posts from @{}", i + 1, len(medias), username)

        self._all_collected.extend(results)
        self._save_json(results, f"user_{username}_{self._timestamp()}.json")
        logger.info("Collected {} posts/reels from @{}", len(results), username)
        return results

    # ------------------------------------------------------------------
    # Reels-specific collection
    # ------------------------------------------------------------------

    def crawl_user_reels(
        self,
        username: str,
        max_reels: int = 30,
        include_comments: bool = True,
    ) -> list[dict]:
        """Crawl only reels from a user."""
        logger.info("=== Crawling reels from @{} ===", username)

        try:
            user_id = self.client.user_id_from_username(username)
            self._delay()
        except Exception as exc:
            logger.error("Failed to resolve @{}: {}", username, exc)
            return []

        try:
            reels = self.client.user_clips(user_id, amount=max_reels)
            logger.info("Fetched {} reels from @{}", len(reels), username)
        except Exception as exc:
            logger.error("Failed to fetch reels from @{}: {}", username, exc)
            return []

        results = []
        for media in reels:
            record = self._media_to_dict(media, source=f"@{username}/reels")
            if include_comments and record["comments_count"] > 0:
                record["comments"] = self.collect_comments(record["media_id"], count=10)
            else:
                record["comments"] = []
            results.append(record)
            self._delay()

        self._all_collected.extend(results)
        self._save_json(results, f"reels_{username}_{self._timestamp()}.json")
        logger.info("Collected {} reels from @{}", len(results), username)
        return results

    # ------------------------------------------------------------------
    # Hashtag search
    # ------------------------------------------------------------------

    def crawl_hashtag(
        self,
        hashtag: str,
        max_posts: int = 50,
        include_comments: bool = False,
    ) -> list[dict]:
        """Crawl recent posts from a hashtag."""
        tag = hashtag.lstrip("#")
        logger.info("=== Crawling #{} (max {} posts) ===", tag, max_posts)

        results = []

        # Recent posts
        try:
            medias = self.client.hashtag_medias_recent(tag, amount=max_posts)
            logger.info("Fetched {} recent posts from #{}", len(medias), tag)
        except Exception as exc:
            logger.error("Failed to fetch #{}: {}", tag, exc)
            return []

        for media in medias:
            record = self._media_to_dict(media, source=f"#{tag}")
            if include_comments and record["comments_count"] > 0:
                record["comments"] = self.collect_comments(record["media_id"], count=5)
            else:
                record["comments"] = []
            results.append(record)
            self._delay()

        # Also try top posts
        try:
            top_medias = self.client.hashtag_medias_top(tag, amount=min(max_posts, 9))
            logger.info("Fetched {} top posts from #{}", len(top_medias), tag)
            for media in top_medias:
                record = self._media_to_dict(media, source=f"#{tag}/top")
                record["comments"] = []
                results.append(record)
                self._delay()
        except Exception as exc:
            logger.warning("Failed to fetch top posts for #{}: {}", tag, exc)

        self._all_collected.extend(results)
        self._save_json(results, f"hashtag_{tag}_{self._timestamp()}.json")
        logger.info("Collected {} posts from #{}", len(results), tag)
        return results

    # ------------------------------------------------------------------
    # Keyword/topic search
    # ------------------------------------------------------------------

    def search_and_crawl(
        self,
        keyword: str,
        max_users: int = 5,
        posts_per_user: int = 30,
    ) -> list[dict]:
        """Search for accounts by keyword and crawl their content."""
        logger.info("=== Searching '{}' and crawling top {} accounts ===", keyword, max_users)

        try:
            users = self.client.search_users(keyword, count=max_users)
            logger.info("Found {} users for '{}'", len(users), keyword)
            self._delay()
        except Exception as exc:
            logger.error("Search failed for '{}': {}", keyword, exc)
            return []

        all_results = []
        for user in users[:max_users]:
            username = user.username
            logger.info("Crawling search result: @{} ({} followers)",
                       username, getattr(user, "follower_count", "?"))
            results = self.crawl_user(username, max_posts=posts_per_user, include_comments=True)
            all_results.extend(results)

        return all_results

    # ------------------------------------------------------------------
    # Explore / trending
    # ------------------------------------------------------------------

    def crawl_explore(self, max_items: int = 30) -> list[dict]:
        """Crawl explore page content."""
        logger.info("=== Crawling Explore page (max {}) ===", max_items)

        results = []
        try:
            # Explore feed
            medias = self.client.explore_page(amount=max_items)
            logger.info("Fetched {} items from explore", len(medias))

            for media in medias:
                if hasattr(media, "media_type"):
                    record = self._media_to_dict(media, source="explore")
                    results.append(record)
                    self._delay()
        except Exception as exc:
            logger.warning("Explore page crawl failed: {}", exc)

        self._all_collected.extend(results)
        if results:
            self._save_json(results, f"explore_{self._timestamp()}.json")
        logger.info("Collected {} items from explore", len(results))
        return results

    # ------------------------------------------------------------------
    # Bulk crawl orchestration
    # ------------------------------------------------------------------

    def bulk_crawl(
        self,
        usernames: list[str] = None,
        hashtags: list[str] = None,
        search_keywords: list[str] = None,
        posts_per_source: int = 30,
        include_explore: bool = True,
    ) -> dict[str, Any]:
        """Run a comprehensive crawl across multiple sources.

        Returns a summary dict with stats.
        """
        logger.info("=" * 60)
        logger.info("BULK CRAWL STARTING")
        logger.info("=" * 60)

        stats = {
            "users_crawled": 0,
            "hashtags_crawled": 0,
            "searches_done": 0,
            "total_posts": 0,
            "total_reels": 0,
            "total_comments": 0,
            "total_items": 0,
        }

        self._all_collected = []

        # Crawl user accounts
        if usernames:
            for username in usernames:
                try:
                    results = self.crawl_user(username, max_posts=posts_per_source)
                    stats["users_crawled"] += 1
                    stats["total_posts"] += len([r for r in results if r["media_type"] == "photo"])
                    stats["total_reels"] += len([r for r in results if r["media_type"] == "reel"])
                    for r in results:
                        stats["total_comments"] += len(r.get("comments", []))
                except Exception as exc:
                    logger.error("Failed to crawl @{}: {}", username, exc)
                    continue

        # Crawl hashtags
        if hashtags:
            for hashtag in hashtags:
                try:
                    results = self.crawl_hashtag(hashtag, max_posts=posts_per_source)
                    stats["hashtags_crawled"] += 1
                except Exception as exc:
                    logger.error("Failed to crawl #{}: {}", hashtag, exc)
                    continue

        # Search and crawl
        if search_keywords:
            for keyword in search_keywords:
                try:
                    results = self.search_and_crawl(keyword, max_users=3, posts_per_user=posts_per_source)
                    stats["searches_done"] += 1
                except Exception as exc:
                    logger.error("Failed to search '{}': {}", keyword, exc)
                    continue

        # Explore page
        if include_explore:
            try:
                self.crawl_explore(max_items=30)
            except Exception:
                pass

        stats["total_items"] = len(self._all_collected)

        # Save combined dataset
        if self._all_collected:
            self._save_json(
                self._all_collected,
                f"bulk_crawl_{self._timestamp()}.json",
            )

        logger.info("=" * 60)
        logger.info("BULK CRAWL COMPLETE")
        logger.info("  Total items: {}", stats["total_items"])
        logger.info("  Posts: {}, Reels: {}", stats["total_posts"], stats["total_reels"])
        logger.info("  Comments collected: {}", stats["total_comments"])
        logger.info("=" * 60)

        return stats

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_json(self, records: list[dict], filename: str) -> Path:
        _RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _RAW_DATA_DIR / filename
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2, default=str)
        logger.info("Saved {} records -> {}", len(records), out_path)
        return out_path

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def get_all_collected(self) -> list[dict]:
        """Return all collected data from this session."""
        return self._all_collected


# Keep backward compatibility
CaptionCollector = InstagramCrawler
