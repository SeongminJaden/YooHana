"""
Post and comment memory system for the AI Influencer.

Stores all posts/comments the bot has written, enabling:
- Context-aware replies (remembering what was posted)
- Answering questions about past content
- Avoiding repetition in future posts
- Maintaining consistent personality across conversations
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MEMORY_DIR = _PROJECT_ROOT / "data" / "memory"
_MEMORY_DIR.mkdir(parents=True, exist_ok=True)


class PostMemory:
    """Persistent memory of all posts and comments the bot has created.

    Stores data in JSON files under ``data/memory/``.
    """

    def __init__(self) -> None:
        self._posts_file = _MEMORY_DIR / "posts.json"
        self._comments_file = _MEMORY_DIR / "comments.json"
        self._posts: list[dict[str, Any]] = self._load(self._posts_file)
        self._comments: list[dict[str, Any]] = self._load(self._comments_file)

    @staticmethod
    def _load(path: Path) -> list[dict]:
        """Load memory from JSON file."""
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save_posts(self) -> None:
        self._posts_file.write_text(
            json.dumps(self._posts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_comments(self) -> None:
        self._comments_file.write_text(
            json.dumps(self._comments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ──────────────────────────────────────────────────────────────
    # Post management
    # ──────────────────────────────────────────────────────────────

    def add_post(
        self,
        caption: str,
        hashtags: list[str] | None = None,
        image_path: str | None = None,
        topic: str | None = None,
        media_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a new post in memory.

        Returns the stored post dict.
        """
        post = {
            "id": len(self._posts) + 1,
            "caption": caption,
            "hashtags": hashtags or [],
            "image_path": image_path,
            "topic": topic,
            "media_id": media_id,
            "created_at": datetime.now().isoformat(),
            "comments_received": [],
        }
        self._posts.append(post)
        self._save_posts()
        logger.info("Post #{} saved to memory", post["id"])
        return post

    def get_recent_posts(self, count: int = 10) -> list[dict[str, Any]]:
        """Get the N most recent posts."""
        return self._posts[-count:]

    def get_all_posts(self) -> list[dict[str, Any]]:
        return list(self._posts)

    def get_recent_captions(self, count: int = 10) -> list[str]:
        """Get captions from recent posts (for repetition avoidance)."""
        return [p["caption"] for p in self._posts[-count:]]

    def find_post_by_topic(self, topic: str) -> list[dict[str, Any]]:
        """Find posts matching a topic keyword."""
        topic_lower = topic.lower()
        results = []
        for post in self._posts:
            caption = post.get("caption", "").lower()
            post_topic = (post.get("topic") or "").lower()
            tags = " ".join(post.get("hashtags", [])).lower()
            if topic_lower in caption or topic_lower in post_topic or topic_lower in tags:
                results.append(post)
        return results

    # ──────────────────────────────────────────────────────────────
    # Comment management
    # ──────────────────────────────────────────────────────────────

    def add_comment(
        self,
        post_id: int | None,
        original_comment: str,
        my_reply: str,
        commenter: str | None = None,
    ) -> dict[str, Any]:
        """Record a comment reply in memory."""
        comment = {
            "id": len(self._comments) + 1,
            "post_id": post_id,
            "commenter": commenter,
            "original_comment": original_comment,
            "my_reply": my_reply,
            "created_at": datetime.now().isoformat(),
        }
        self._comments.append(comment)
        self._save_comments()

        # Also link to the post if it exists
        if post_id is not None:
            for post in self._posts:
                if post["id"] == post_id:
                    post.setdefault("comments_received", []).append({
                        "commenter": commenter,
                        "comment": original_comment,
                        "reply": my_reply,
                    })
                    self._save_posts()
                    break

        logger.debug("Comment reply #{} saved to memory", comment["id"])
        return comment

    def get_recent_comments(self, count: int = 20) -> list[dict[str, Any]]:
        """Get the N most recent comment replies."""
        return self._comments[-count:]

    def get_comments_for_post(self, post_id: int) -> list[dict[str, Any]]:
        """Get all comment replies for a specific post."""
        return [c for c in self._comments if c.get("post_id") == post_id]

    # ──────────────────────────────────────────────────────────────
    # Context building (for LLM prompts)
    # ──────────────────────────────────────────────────────────────

    def build_post_context(self, max_posts: int = 5) -> str:
        """Build a context string of recent posts for the LLM.

        Used to help the model:
        - Avoid repeating topics
        - Reference past content when replying
        - Maintain consistency
        """
        recent = self.get_recent_posts(max_posts)
        if not recent:
            return ""

        lines = ["[최근 내가 올린 게시글]"]
        for post in recent:
            date = post.get("created_at", "")[:10]
            caption = post["caption"][:100]
            lines.append(f"- ({date}) {caption}")

        return "\n".join(lines)

    def build_comment_context(self, max_comments: int = 10) -> str:
        """Build a context string of recent comment replies."""
        recent = self.get_recent_comments(max_comments)
        if not recent:
            return ""

        lines = ["[최근 내가 단 답글]"]
        for c in recent:
            orig = c.get("original_comment", "")[:50]
            reply = c.get("my_reply", "")[:50]
            lines.append(f"- 댓글: '{orig}' → 내 답글: '{reply}'")

        return "\n".join(lines)

    def build_full_context(self, max_posts: int = 5, max_comments: int = 10) -> str:
        """Build complete context for LLM generation."""
        parts = []
        post_ctx = self.build_post_context(max_posts)
        if post_ctx:
            parts.append(post_ctx)
        comment_ctx = self.build_comment_context(max_comments)
        if comment_ctx:
            parts.append(comment_ctx)
        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────
    # Stats
    # ──────────────────────────────────────────────────────────────

    @property
    def total_posts(self) -> int:
        return len(self._posts)

    @property
    def total_comments(self) -> int:
        return len(self._comments)

    def summary(self) -> str:
        """Return a brief summary of memory contents."""
        return (
            f"게시글 {self.total_posts}개, "
            f"댓글 답글 {self.total_comments}개 기억 중"
        )
