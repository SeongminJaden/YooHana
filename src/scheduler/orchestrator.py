"""
Main scheduler / orchestrator for the AI Influencer pipeline.

Coordinates all components — persona, text generation, image generation,
Instagram posting, content planning, and comment handling — on a
repeating schedule powered by APScheduler.
"""

from __future__ import annotations

import random
import signal
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.persona.character import Persona
from src.planner.content_planner import ContentPlanner
from src.planner.topic_generator import TopicGenerator
from src.scheduler.task_queue import Task, TaskQueue
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict:
    """Load a YAML config file and return its contents as a dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Orchestrator:
    """Central scheduler that drives the entire AI Influencer pipeline.

    On ``start()`` it launches an APScheduler event loop with jobs for:
    - Weekly content planning (Monday 06:00 KST + jitter)
    - Hourly posting checks
    - Comment monitoring (30 min peak / 2 h off-peak + jitter)

    All errors are caught, logged, and (where applicable) pushed to the
    ``TaskQueue`` for retry.
    """

    def __init__(self) -> None:
        # Load configs
        self._schedule_cfg = _load_yaml(_CONFIG_DIR / "schedule.yaml")
        self._settings_cfg = _load_yaml(_CONFIG_DIR / "settings.yaml")

        # Timezone
        self._tz: str = self._schedule_cfg.get("timezone", "Asia/Seoul")

        # Jitter
        self._jitter: int = self._schedule_cfg.get("jitter_minutes", 15)

        # Core components (lazy-initialised in _init_components)
        self.persona: Persona | None = None
        self.text_generator: Any = None
        self.image_client: Any = None
        self.poster: Any = None
        self.content_planner: ContentPlanner | None = None
        self.topic_generator: TopicGenerator | None = None
        self.task_queue: TaskQueue = TaskQueue()

        # APScheduler
        self._scheduler: BlockingScheduler | None = None

        # Trend analysis components
        self.trend_scraper: Any = None
        self.media_analyzer: Any = None
        self.trend_detector: Any = None
        self.reel_creator: Any = None

        # State tracking
        self._running: bool = False
        self._posts_today: int = 0
        self._reels_today: int = 0
        self._last_post_date: str = ""

        # Initialise components
        self._init_components()

    # ------------------------------------------------------------------
    # Component initialisation
    # ------------------------------------------------------------------

    def _init_components(self) -> None:
        """Instantiate all pipeline components.

        Components that depend on external services (image generation,
        Instagram API) are initialised as *None* placeholders when the
        respective modules are not yet implemented.  The orchestrator
        logs a warning and continues — this allows the scheduler logic
        to be tested independently.
        """
        # Persona (always available)
        try:
            self.persona = Persona()
            logger.info("Persona loaded: {}", self.persona.name)
        except Exception as exc:
            logger.error("Failed to load persona: {}", exc)
            raise

        # Text generator (inference module — may not exist yet)
        try:
            from src.inference import TextGenerator  # type: ignore[attr-defined]

            self.text_generator = TextGenerator(self.persona)
            logger.info("TextGenerator initialised")
        except (ImportError, Exception) as exc:
            logger.warning(
                "TextGenerator not available ({}). Running without text generation.",
                exc,
            )
            self.text_generator = None

        # Image client (image_gen module — may not exist yet)
        try:
            from src.image_gen import ImageClient  # type: ignore[attr-defined]

            self.image_client = ImageClient()
            logger.info("ImageClient initialised")
        except (ImportError, Exception) as exc:
            logger.warning(
                "ImageClient not available ({}). Running without image generation.",
                exc,
            )
            self.image_client = None

        # Instagram poster (instagram module — may not exist yet)
        try:
            from src.instagram import InstagramPoster  # type: ignore[attr-defined]

            self.poster = InstagramPoster()
            logger.info("InstagramPoster initialised")
        except (ImportError, Exception) as exc:
            logger.warning(
                "InstagramPoster not available ({}). Running without posting.",
                exc,
            )
            self.poster = None

        # Content planner & topic generator
        self.topic_generator = TopicGenerator(self.persona)
        self.content_planner = ContentPlanner(self.text_generator, self.persona)
        logger.info("ContentPlanner and TopicGenerator initialised")

        # Trend analysis components
        trend_cfg = self._settings_cfg.get("trend_analysis", {})
        if trend_cfg.get("enabled", False):
            try:
                from src.trend_analyzer.scraper import TrendScraper
                from src.trend_analyzer.media_analyzer import MediaAnalyzer
                from src.trend_analyzer.trend_detector import TrendDetector
                from src.trend_analyzer.reel_creator import ReelCreator

                self.trend_scraper = TrendScraper()
                self.media_analyzer = MediaAnalyzer()
                self.trend_detector = TrendDetector()
                self.reel_creator = ReelCreator(
                    self.persona, self.text_generator, self.image_client
                )
                logger.info("Trend analysis components initialised")
            except (ImportError, Exception) as exc:
                logger.warning(
                    "Trend analysis not available ({}). Running without trend features.",
                    exc,
                )

    # ------------------------------------------------------------------
    # Schedule setup
    # ------------------------------------------------------------------

    def setup_schedules(self) -> None:
        """Configure APScheduler jobs based on ``schedule.yaml``.

        Jobs
        ----
        - **weekly_planning**: Monday at 06:00 KST (+ random jitter).
        - **posting_check**: every ``posting.check_interval_minutes`` minutes.
        - **comment_check_peak**: every ``comments.check_interval_minutes``
          minutes during peak hours.
        - **comment_check_offpeak**: every ``comments.off_peak_interval_minutes``
          minutes outside peak hours.

        All interval jobs receive +-jitter_minutes of random offset.
        """
        self._scheduler = BlockingScheduler(timezone=self._tz)

        planning = self._schedule_cfg.get("planning", {}).get("weekly", {})
        posting = self._schedule_cfg.get("posting", {})
        comments = self._schedule_cfg.get("comments", {})

        # --- Weekly planning (cron) ---
        jitter_offset = random.randint(-self._jitter, self._jitter)
        plan_minute = (planning.get("minute", 0) + jitter_offset) % 60
        plan_hour = planning.get("hour", 6)
        plan_day = planning.get("day", "monday")[:3].lower()  # e.g. "mon"

        self._scheduler.add_job(
            self._safe_run(self.run_weekly_planning),
            CronTrigger(
                day_of_week=plan_day,
                hour=plan_hour,
                minute=plan_minute,
                timezone=self._tz,
            ),
            id="weekly_planning",
            name="Weekly Content Planning",
            replace_existing=True,
        )
        logger.info(
            "Scheduled weekly planning: {} {:02d}:{:02d} ({})",
            plan_day.upper(),
            plan_hour,
            plan_minute,
            self._tz,
        )

        # --- Posting check (interval) ---
        post_interval = posting.get("check_interval_minutes", 60)
        post_jitter = random.randint(0, self._jitter)

        self._scheduler.add_job(
            self._safe_run(self.run_posting_cycle),
            IntervalTrigger(
                minutes=post_interval,
                timezone=self._tz,
                jitter=post_jitter * 60,  # APScheduler jitter is in seconds
            ),
            id="posting_check",
            name="Posting Check",
            replace_existing=True,
        )
        logger.info(
            "Scheduled posting check: every {}min (jitter ±{}min)",
            post_interval,
            post_jitter,
        )

        # --- Comment monitoring: peak hours ---
        comment_interval = comments.get("check_interval_minutes", 30)
        peak_start = comments.get("peak_hours", {}).get("start", 10)
        peak_end = comments.get("peak_hours", {}).get("end", 22)
        comment_jitter = random.randint(0, self._jitter)

        self._scheduler.add_job(
            self._safe_run(self.run_comment_cycle),
            CronTrigger(
                minute=f"*/{comment_interval}",
                hour=f"{peak_start}-{peak_end - 1}",
                timezone=self._tz,
                jitter=comment_jitter * 60,
            ),
            id="comment_check_peak",
            name="Comment Monitor (Peak)",
            replace_existing=True,
        )
        logger.info(
            "Scheduled peak comment check: every {}min, hours {}-{} (jitter ±{}min)",
            comment_interval,
            peak_start,
            peak_end,
            comment_jitter,
        )

        # --- Comment monitoring: off-peak hours ---
        offpeak_interval = comments.get("off_peak_interval_minutes", 120)
        offpeak_jitter = random.randint(0, self._jitter)

        # Off-peak = outside peak window
        offpeak_hours = ",".join(
            str(h)
            for h in range(24)
            if h < peak_start or h >= peak_end
        )

        self._scheduler.add_job(
            self._safe_run(self.run_comment_cycle),
            CronTrigger(
                minute=f"*/{offpeak_interval}",
                hour=offpeak_hours,
                timezone=self._tz,
                jitter=offpeak_jitter * 60,
            ),
            id="comment_check_offpeak",
            name="Comment Monitor (Off-Peak)",
            replace_existing=True,
        )
        logger.info(
            "Scheduled off-peak comment check: every {}min (jitter ±{}min)",
            offpeak_interval,
            offpeak_jitter,
        )

        # --- Trend analysis (interval) ---
        trend_cfg = self._schedule_cfg.get("trend_analysis", {})
        trend_interval_hours = trend_cfg.get("check_interval_hours", 6)
        trend_jitter = random.randint(0, self._jitter)

        self._scheduler.add_job(
            self._safe_run(self.run_trend_analysis_cycle),
            IntervalTrigger(
                hours=trend_interval_hours,
                timezone=self._tz,
                jitter=trend_jitter * 60,
            ),
            id="trend_analysis",
            name="Trend Analysis & Reel Creation",
            replace_existing=True,
        )
        logger.info(
            "Scheduled trend analysis: every {}h (jitter ±{}min)",
            trend_interval_hours,
            trend_jitter,
        )

        # --- Task queue processor (every 5 min) ---
        self._scheduler.add_job(
            self._safe_run(self._process_task_queue),
            IntervalTrigger(minutes=5, timezone=self._tz),
            id="task_queue_processor",
            name="Task Queue Processor",
            replace_existing=True,
        )
        logger.info("Scheduled task queue processor: every 5min")

    # ------------------------------------------------------------------
    # Core cycles
    # ------------------------------------------------------------------

    def run_weekly_planning(self) -> None:
        """Generate and save the weekly content plan."""
        logger.info("=== Starting weekly content planning ===")

        if self.content_planner is None:
            logger.error("ContentPlanner not initialised — skipping planning")
            return

        plan = self.content_planner.generate_weekly_plan()
        self.content_planner.save_plan(plan)
        logger.info("Weekly plan saved ({} items)", len(plan))

    def run_posting_cycle(self) -> None:
        """Check if a post should go out now, then generate and publish it.

        Steps
        -----
        1. Check daily post limit.
        2. Check if current hour is an optimal posting hour.
        3. Fetch today's planned content (or generate ad-hoc).
        4. Generate image.
        5. Generate caption.
        6. Post to Instagram.
        """
        logger.info("--- Posting cycle started ---")

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_hour = now.hour

        # Reset daily counter
        if self._last_post_date != today_str:
            self._posts_today = 0
            self._last_post_date = today_str

        # Check daily limit
        max_posts = (
            self._schedule_cfg.get("posting", {}).get("max_posts_per_day", 2)
        )
        if self._posts_today >= max_posts:
            logger.info("Daily post limit reached ({}/{})", self._posts_today, max_posts)
            return

        # Check optimal hours
        is_weekend = now.weekday() >= 5
        optimal_key = "weekend" if is_weekend else "weekday"
        optimal_hours: list[int] = (
            self._schedule_cfg.get("posting", {}).get("optimal_hours", {}).get(
                optimal_key, []
            )
        )
        if current_hour not in optimal_hours:
            logger.debug(
                "Hour {} not in optimal hours {} — skipping",
                current_hour,
                optimal_hours,
            )
            return

        # Get content plan for today
        content: dict | None = None
        if self.content_planner:
            content = self.content_planner.get_todays_content()

        if content is None:
            logger.info("No planned content for today — generating ad-hoc topic")
            if self.topic_generator:
                topics = self.topic_generator.generate_topics(count=1)
                topic = topics[0] if topics else "일상 기록"
            else:
                topic = "일상 기록"
            content = {
                "topic": topic,
                "scene": "in a natural, everyday setting in Seoul",
                "mood": "bright and natural",
                "hashtags": [],
                "post_type": "feed",
            }

        logger.info("Posting content: {}", content.get("topic", "unknown"))

        # Generate image
        image_path: str | None = None
        if self.image_client:
            try:
                scene = content.get("scene", "")
                image_prompt = self.persona.get_image_prompt(scene) if self.persona else scene
                image_path = self.image_client.generate(image_prompt)
                logger.info("Image generated: {}", image_path)
            except Exception as exc:
                logger.error("Image generation failed: {}", exc)
                self.task_queue.add_task(
                    "retry_image",
                    {"content": content, "error": str(exc)},
                    priority=3,
                )
                return
        else:
            logger.warning("No ImageClient — skipping image generation")

        # Generate caption
        caption: str = ""
        if self.text_generator and self.persona:
            try:
                instruction = self.persona.get_caption_instruction(content["topic"])
                caption = self.text_generator.generate(instruction)
                logger.info("Caption generated ({} chars)", len(caption))
            except Exception as exc:
                logger.error("Caption generation failed: {}", exc)
                caption = ""

        # Append hashtags
        hashtags = content.get("hashtags", [])
        if not hashtags and self.topic_generator:
            hashtags = self.topic_generator.generate_hashtags(content["topic"])
        if hashtags:
            caption = f"{caption}\n\n{' '.join(hashtags)}" if caption else " ".join(hashtags)

        # Post to Instagram
        if self.poster and image_path:
            try:
                post_type = content.get("post_type", "feed")
                if post_type == "story":
                    self.poster.post_story(image_path, caption)
                else:
                    self.poster.post_feed(image_path, caption)

                self._posts_today += 1
                logger.info(
                    "Posted successfully ({}/{} today): {}",
                    self._posts_today,
                    max_posts,
                    content["topic"],
                )
            except Exception as exc:
                logger.error("Posting failed: {}", exc)
                self.task_queue.add_task(
                    "retry_post",
                    {
                        "image_path": image_path,
                        "caption": caption,
                        "error": str(exc),
                    },
                    priority=3,
                )
        else:
            logger.warning(
                "Posting skipped (poster={}, image_path={})",
                self.poster is not None,
                image_path,
            )

    def run_trend_analysis_cycle(self) -> None:
        """Analyze trending reels/posts and create trend-based content.

        Steps
        -----
        1. Scrape trending reels and posts from explore page.
        2. Download and analyze media (visuals, audio, music, voice).
        3. Detect patterns across trending content.
        4. Generate a content brief adapted to persona.
        5. Create and post a reel or trend-based post.
        """
        logger.info("--- Trend analysis cycle started ---")

        if not self.trend_scraper or not self.trend_detector:
            logger.warning("Trend analysis components not available — skipping")
            return

        # Check daily reel limit
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        if self._last_post_date != today_str:
            self._reels_today = 0

        max_reels = self._settings_cfg.get("trend_analysis", {}).get("max_reels_per_day", 1)
        if self._reels_today >= max_reels:
            logger.info("Daily reel limit reached ({}/{})", self._reels_today, max_reels)
            return

        try:
            # Step 1: Scrape trending content
            scrape_count = self._settings_cfg.get("trend_analysis", {}).get("scrape_count", 20)
            logger.info("Scraping {} trending reels/posts...", scrape_count)
            trending_reels = self.trend_scraper.get_trending_reels(count=scrape_count)
            trending_posts = self.trend_scraper.get_trending_posts(count=scrape_count)

            all_trending = trending_reels + trending_posts
            if not all_trending:
                logger.warning("No trending content found")
                return

            # Step 2: Rank by engagement
            ranked = self.trend_detector.rank_by_engagement(all_trending)
            min_score = self._settings_cfg.get("trend_analysis", {}).get("min_engagement_score", 100)
            top_items = [item for item in ranked[:10]]

            logger.info("Found {} high-engagement items", len(top_items))

            # Step 3: Download and analyze top items
            analyses = []
            for item in top_items[:5]:
                try:
                    media_id = item.get("media_id", "")
                    analysis = {"metadata": item}

                    # Download and analyze video for reels
                    if item.get("media_type") == "reel" and self.media_analyzer:
                        video_path = self.trend_scraper.download_reel(media_id)
                        if video_path:
                            media_analysis = self.media_analyzer.full_analysis(
                                video_path, item.get("caption", "")
                            )
                            analysis.update(media_analysis)
                    else:
                        # Analyze caption style for posts
                        if self.media_analyzer:
                            caption_analysis = self.media_analyzer.analyze_caption_style(
                                item.get("caption", "")
                            )
                            analysis["caption_analysis"] = caption_analysis

                            # Download and analyze thumbnail
                            thumb_path = self.trend_scraper.download_thumbnail(media_id)
                            if thumb_path:
                                thumb_analysis = self.media_analyzer.analyze_thumbnail(thumb_path)
                                analysis["visual"] = thumb_analysis

                    analyses.append(analysis)
                except Exception as exc:
                    logger.warning("Failed to analyze item {}: {}", item.get("media_id"), exc)
                    continue

            if not analyses:
                logger.warning("No items could be analyzed")
                return

            # Step 4: Detect patterns
            patterns = self.trend_detector.detect_patterns(analyses)
            logger.info("Detected patterns: {} visual, {} audio, {} caption trends",
                       len(patterns.get("visual_trends", [])),
                       len(patterns.get("audio_trends", [])),
                       len(patterns.get("caption_trends", [])))

            # Get trending audio
            trending_audio = self.trend_detector.get_trending_audio_ids(all_trending)
            if trending_audio:
                patterns["trending_audio"] = trending_audio[:3]

            # Step 5: Generate content brief
            brief = self.trend_detector.generate_content_brief(patterns, self.persona)
            logger.info("Content brief generated: topic='{}', style='{}'",
                       brief.get("topic", ""), brief.get("visual_style", ""))

            # Step 6: Create reel/post content
            if self.reel_creator:
                content = self.reel_creator.create_reel_content(brief)

                if content and content.get("frames"):
                    # Compose into video
                    duration = self.reel_creator.get_optimal_duration(patterns)
                    video_path = self.reel_creator.compose_reel_video(
                        content["frames"],
                        duration=duration,
                        transition=patterns.get("recommended_style", {}).get("transition", "fade"),
                    )

                    if video_path and self.poster:
                        # Post the reel
                        caption = content.get("caption", "")
                        hashtags = content.get("hashtags", [])
                        if hashtags:
                            caption = f"{caption}\n\n{' '.join(hashtags)}"

                        try:
                            self.poster.post_reel(video_path, caption)
                            self._reels_today += 1
                            logger.info(
                                "Trend-based reel posted ({}/{}): {}",
                                self._reels_today, max_reels, brief.get("topic", "")
                            )
                        except Exception as exc:
                            logger.error("Reel posting failed: {}", exc)
                            self.task_queue.add_task(
                                "retry_reel", {"video_path": video_path, "caption": caption},
                                priority=3,
                            )
                else:
                    logger.warning("Reel content creation returned no frames")
            else:
                logger.warning("ReelCreator not available — skipping reel creation")

        except Exception as exc:
            logger.error("Trend analysis cycle failed: {}", exc)
            self.task_queue.add_task("retry_trend", {"error": str(exc)}, priority=5)

    def run_comment_cycle(self) -> None:
        """Check for unreplied comments, generate replies, and post them.

        Steps
        -----
        1. Fetch recent comments via Instagram API.
        2. Filter to unreplied ones.
        3. Generate reply text using the persona.
        4. Post replies.
        """
        logger.info("--- Comment cycle started ---")

        if not self.poster:
            logger.warning("No InstagramPoster — skipping comment cycle")
            return

        max_replies = (
            self._schedule_cfg.get("comments", {}).get("max_replies_per_check", 5)
        )

        try:
            # Fetch unreplied comments (interface depends on poster impl)
            unreplied = self.poster.get_unreplied_comments()  # type: ignore[attr-defined]
        except (AttributeError, Exception) as exc:
            logger.warning("Could not fetch unreplied comments: {}", exc)
            return

        if not unreplied:
            logger.debug("No unreplied comments found")
            return

        logger.info("Found {} unreplied comments", len(unreplied))
        replied_count = 0

        for comment in unreplied[:max_replies]:
            comment_text = comment.get("text", "")
            comment_id = comment.get("id", "unknown")

            if not comment_text:
                continue

            # Generate reply
            reply_text = ""
            if self.text_generator and self.persona:
                try:
                    instruction = self.persona.get_reply_instruction(comment_text)
                    reply_text = self.text_generator.generate(instruction)
                except Exception as exc:
                    logger.error("Reply generation failed for comment {}: {}", comment_id, exc)
                    self.task_queue.add_task(
                        "retry_reply",
                        {"comment": comment, "error": str(exc)},
                        priority=1,  # Urgent
                    )
                    continue

            if not reply_text:
                logger.warning("Empty reply for comment {} — skipping", comment_id)
                continue

            # Post reply
            try:
                self.poster.reply_to_comment(comment_id, reply_text)  # type: ignore[attr-defined]
                replied_count += 1
                logger.info(
                    "Replied to comment {} ({}/{})",
                    comment_id,
                    replied_count,
                    max_replies,
                )
            except Exception as exc:
                logger.error("Failed to post reply to {}: {}", comment_id, exc)
                self.task_queue.add_task(
                    "retry_reply",
                    {
                        "comment_id": comment_id,
                        "reply_text": reply_text,
                        "error": str(exc),
                    },
                    priority=1,
                )

        logger.info("Comment cycle complete: replied to {}/{}", replied_count, len(unreplied))

    # ------------------------------------------------------------------
    # Task queue processing
    # ------------------------------------------------------------------

    def _process_task_queue(self) -> None:
        """Process pending tasks from the priority queue."""
        pending = self.task_queue.get_pending_count()
        if pending == 0:
            return

        logger.info("Processing task queue ({} pending)", pending)

        task = self.task_queue.get_next()
        while task is not None:
            try:
                self._execute_task(task)
                self.task_queue.complete_task(task.id)
            except Exception as exc:
                logger.error("Task {} failed: {}", task.id, exc)
                self.task_queue.fail_task(task.id, str(exc))

            task = self.task_queue.get_next()

    def _execute_task(self, task: Task) -> None:
        """Execute a single task based on its type."""
        logger.info("Executing task: {} (type={}, priority={})", task.id, task.type, task.priority)

        if task.type == "retry_post":
            self.run_posting_cycle()
        elif task.type == "retry_reply":
            comment = task.payload.get("comment")
            if comment:
                # Re-attempt a single comment reply
                pass  # Will be handled in next comment cycle
        elif task.type == "retry_image":
            # Re-attempt image generation
            pass  # Will be handled in next posting cycle
        else:
            logger.warning("Unknown task type: {}", task.type)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler loop.

        Registers signal handlers for graceful shutdown and begins the
        APScheduler blocking loop.
        """
        logger.info("====== AI Influencer Orchestrator starting ======")
        logger.info("Timezone: {}", self._tz)
        logger.info("Jitter: ±{}min", self._jitter)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.setup_schedules()

        self._running = True
        logger.info("Scheduler loop starting...")

        try:
            if self._scheduler:
                self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self) -> None:
        """Gracefully shut down the scheduler and all components."""
        logger.info("====== Orchestrator shutting down ======")
        self._running = False

        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("APScheduler shut down")

        # Log final task queue state
        pending = self.task_queue.get_pending_count()
        if pending > 0:
            logger.warning("{} tasks still pending in queue", pending)

        logger.info("Orchestrator stopped")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle OS signals for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("Received signal {} — initiating shutdown", sig_name)
        self.stop()

    # ------------------------------------------------------------------
    # Error-safe wrapper
    # ------------------------------------------------------------------

    def _safe_run(self, func: Any) -> Any:
        """Wrap a callable so that all exceptions are caught and logged.

        Returns a new callable that never raises (APScheduler would
        otherwise silently swallow the job on repeated failures).
        """

        def wrapper(*args: Any, **kwargs: Any) -> None:
            try:
                func(*args, **kwargs)
            except Exception:
                logger.error(
                    "Unhandled error in {}: {}",
                    func.__name__,
                    traceback.format_exc(),
                )

        wrapper.__name__ = func.__name__
        return wrapper
