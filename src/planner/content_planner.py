"""
Weekly content planning for the AI Influencer.

Generates 7-14 content ideas per week, considering persona themes,
current season, Korean holidays, and recent post history to avoid
repetition.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from src.persona.character import Persona
from src.planner.topic_generator import TopicGenerator
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"
_DEFAULT_PLAN_PATH = _PROJECT_ROOT / "data" / "weekly_plan.json"


class ContentPlanner:
    """Plan a week's worth of Instagram content aligned with the persona.

    Parameters
    ----------
    text_generator
        Any object that exposes a ``generate(prompt: str) -> str`` method
        (e.g. an inference TextGenerator). Used to brainstorm fresh topics
        when needed. Can be *None* for offline/template-based planning.
    persona : Persona
        The loaded persona instance that defines themes, tone, and boundaries.
    """

    def __init__(self, text_generator: Any, persona: Persona) -> None:
        self.text_generator = text_generator
        self.persona = persona
        self.topic_generator = TopicGenerator(persona)

        # Load schedule config for optimal posting hours
        schedule_path = _CONFIG_DIR / "schedule.yaml"
        with open(schedule_path, "r", encoding="utf-8") as f:
            self._schedule_cfg: dict = yaml.safe_load(f)

    # ------------------------------------------------------------------
    # Weekly plan generation
    # ------------------------------------------------------------------

    def generate_weekly_plan(
        self,
        recent_posts: list[str] | None = None,
    ) -> list[dict]:
        """Generate 7-14 content ideas for the upcoming week.

        Each item contains day, topic, scene, mood, hashtags, and post_type.
        The planner avoids repeating themes present in *recent_posts* and
        factors in season and Korean holidays.

        Parameters
        ----------
        recent_posts : list[str] | None
            Topics / captions of recent posts to avoid repetition.

        Returns
        -------
        list[dict]
            A list of 7-14 content plan dicts, one or two per day.
        """
        recent_posts = recent_posts or []
        recent_lower = {p.lower() for p in recent_posts}

        # Gather candidate topics
        seasonal_topics = self.topic_generator.get_seasonal_topics()
        holiday_entries = self.topic_generator.get_korean_holidays()
        general_topics = self.topic_generator.generate_topics(count=14)

        # Build the week starting from next Monday (or today if Monday)
        today = datetime.now()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            start_date = today
        else:
            start_date = today + timedelta(days=days_until_monday)

        plan: list[dict] = []
        used_topics: set[str] = set()

        # Determine how many posts per day (1 or 2)
        max_posts = self._schedule_cfg.get("posting", {}).get("max_posts_per_day", 2)

        for day_offset in range(7):
            target_date = start_date + timedelta(days=day_offset)
            day_name = target_date.strftime("%A")
            date_str = target_date.strftime("%Y-%m-%d")
            is_weekend = target_date.weekday() >= 5

            # Decide 1 or 2 posts for this day
            num_posts = random.choice([1, max_posts]) if max_posts > 1 else 1

            for post_idx in range(num_posts):
                topic = self._pick_topic(
                    day_offset=day_offset,
                    target_date=target_date,
                    seasonal_topics=seasonal_topics,
                    holiday_entries=holiday_entries,
                    general_topics=general_topics,
                    recent_lower=recent_lower,
                    used_topics=used_topics,
                )
                used_topics.add(topic.lower())

                scene = self._topic_to_scene(topic)
                mood = self._topic_to_mood(topic)
                hashtags = self.topic_generator.generate_hashtags(topic)
                post_type = self._decide_post_type(post_idx, is_weekend)

                entry = {
                    "day": f"{day_name} ({date_str})",
                    "topic": topic,
                    "scene": scene,
                    "mood": mood,
                    "hashtags": hashtags,
                    "post_type": post_type,
                }
                plan.append(entry)

        logger.info(
            "Generated weekly plan with {} content items for {} ~ {}",
            len(plan),
            start_date.strftime("%Y-%m-%d"),
            (start_date + timedelta(days=6)).strftime("%Y-%m-%d"),
        )
        return plan

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_plan(
        self,
        plan: list[dict],
        path: str = "data/weekly_plan.json",
    ) -> None:
        """Save the weekly plan to a JSON file.

        Parameters
        ----------
        plan : list[dict]
            The plan list produced by ``generate_weekly_plan()``.
        path : str
            File path relative to the project root (or absolute).
        """
        save_path = Path(path)
        if not save_path.is_absolute():
            save_path = _PROJECT_ROOT / save_path

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        logger.info("Weekly plan saved to {}", save_path)

    def load_plan(
        self,
        path: str = "data/weekly_plan.json",
    ) -> list[dict]:
        """Load a previously saved weekly plan from JSON.

        Parameters
        ----------
        path : str
            File path relative to the project root (or absolute).

        Returns
        -------
        list[dict]
            The loaded plan list.  Returns an empty list if the file does
            not exist.
        """
        load_path = Path(path)
        if not load_path.is_absolute():
            load_path = _PROJECT_ROOT / load_path

        if not load_path.exists():
            logger.warning("Plan file not found: {}", load_path)
            return []

        with open(load_path, "r", encoding="utf-8") as f:
            plan: list[dict] = json.load(f)

        logger.info("Loaded weekly plan with {} items from {}", len(plan), load_path)
        return plan

    # ------------------------------------------------------------------
    # Today's content
    # ------------------------------------------------------------------

    def get_todays_content(self) -> dict | None:
        """Return the first planned content entry for today.

        Loads the default weekly plan and searches for an entry whose
        ``day`` field contains today's date string (``YYYY-MM-DD``).

        Returns
        -------
        dict | None
            The matching content dict, or *None* if nothing is planned.
        """
        plan = self.load_plan()
        if not plan:
            return None

        today_str = datetime.now().strftime("%Y-%m-%d")

        for entry in plan:
            if today_str in entry.get("day", ""):
                logger.info("Today's content: {}", entry["topic"])
                return entry

        logger.info("No content planned for today ({})", today_str)
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _pick_topic(
        self,
        day_offset: int,
        target_date: datetime,
        seasonal_topics: list[str],
        holiday_entries: list[dict],
        general_topics: list[str],
        recent_lower: set[str],
        used_topics: set[str],
    ) -> str:
        """Select a topic for a specific day, avoiding duplicates."""

        # Check if there is a holiday on this date
        date_str = target_date.strftime("%m-%d")
        for holiday in holiday_entries:
            if holiday.get("date", "").endswith(date_str):
                idea = holiday.get("content_idea", holiday["name"])
                if idea.lower() not in used_topics and idea.lower() not in recent_lower:
                    return idea

        # Build candidate pool: mix seasonal and general topics
        candidates: list[str] = []
        candidates.extend(seasonal_topics)
        candidates.extend(general_topics)

        # Filter out already-used and recent topics
        filtered = [
            t
            for t in candidates
            if t.lower() not in used_topics and t.lower() not in recent_lower
        ]

        if filtered:
            return random.choice(filtered)

        # Fallback: return a general topic even if slightly similar
        if general_topics:
            return random.choice(general_topics)

        return "일상 기록"

    @staticmethod
    def _topic_to_scene(topic: str) -> str:
        """Map a topic string to a plausible scene description for image gen."""
        scene_map: dict[str, str] = {
            "카페": "sitting in a cozy Korean cafe with latte art on the table",
            "패션": "standing on a trendy Seoul street, full-body outfit shot",
            "맛집": "at a beautifully plated restaurant table in Seoul",
            "서울": "walking through a scenic Seoul neighbourhood",
            "OOTD": "posing in front of a minimalist wall, full-body mirror selfie",
            "벚꽃": "under blooming cherry blossom trees in a Seoul park",
            "바다": "at a Korean beach with clear blue sky",
            "단풍": "walking through autumn foliage in a Korean park",
            "크리스마스": "in a warmly decorated Christmas setting with fairy lights",
            "피크닉": "having a picnic on a sunny day in a Seoul park",
            "음악": "wearing headphones in a cozy room with vinyl records",
            "자기계발": "reading a book in a bright, modern study space",
            "여행": "exploring a scenic travel destination with a backpack",
        }

        for keyword, scene in scene_map.items():
            if keyword in topic:
                return scene

        return "in a natural, everyday setting in Seoul"

    @staticmethod
    def _topic_to_mood(topic: str) -> str:
        """Infer a mood / aesthetic keyword from the topic."""
        mood_map: dict[str, str] = {
            "카페": "warm and cozy",
            "패션": "confident and stylish",
            "맛집": "happy and indulgent",
            "벚꽃": "dreamy and romantic",
            "바다": "refreshing and free",
            "단풍": "nostalgic and warm",
            "크리스마스": "festive and joyful",
            "음악": "chill and introspective",
            "자기계발": "motivated and focused",
            "여행": "adventurous and curious",
            "피크닉": "bright and relaxed",
        }

        for keyword, mood in mood_map.items():
            if keyword in topic:
                return mood

        return "bright and natural"

    @staticmethod
    def _decide_post_type(post_index: int, is_weekend: bool) -> str:
        """Decide between 'feed' and 'story' for a post slot.

        The first post of the day is usually a feed post. Second posts
        lean toward stories, especially on weekends.
        """
        if post_index == 0:
            return "feed"
        if is_weekend:
            return random.choice(["story", "story", "feed"])
        return random.choice(["story", "feed"])
