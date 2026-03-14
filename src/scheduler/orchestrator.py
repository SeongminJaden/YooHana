"""
Main scheduler / orchestrator for the AI Influencer pipeline.

Coordinates all components — persona, text generation, image generation,
Instagram posting, and comment handling — on a repeating schedule
powered by APScheduler.
"""

from __future__ import annotations

import random
import signal
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
        self.commenter: Any = None
        self.content_planner: ContentPlanner | None = None
        self.topic_generator: TopicGenerator | None = None
        self.task_queue: TaskQueue = TaskQueue()

        # APScheduler
        self._scheduler: BlockingScheduler | None = None

        # State tracking
        self._running: bool = False
        self._posts_today: int = 0
        self._last_post_date: str = ""

        # Initialise components
        self._init_components()

    # ------------------------------------------------------------------
    # Component initialisation
    # ------------------------------------------------------------------

    def _init_components(self) -> None:
        """Instantiate all pipeline components.

        Components that depend on external services are initialised with
        fallback warnings so the scheduler can be tested independently.
        """
        # Persona (always available)
        try:
            self.persona = Persona()
            logger.info("Persona loaded: {}", self.persona.name)
        except Exception as exc:
            logger.error("Failed to load persona: {}", exc)
            raise

        # Text generator
        try:
            from src.inference.text_generator import TextGenerator

            self.text_generator = TextGenerator()
            logger.info("TextGenerator 초기화 완료")
        except (ImportError, Exception) as exc:
            logger.warning(
                "TextGenerator 사용 불가 ({}). 텍스트 생성 없이 실행.",
                exc,
            )
            self.text_generator = None

        # Image client (Gemini API)
        try:
            from src.image_gen.gemini_client import GeminiImageClient

            self.image_client = GeminiImageClient()
            logger.info("GeminiImageClient 초기화 완료")
        except (ImportError, Exception) as exc:
            logger.warning(
                "GeminiImageClient 사용 불가 ({}). 이미지 생성 없이 실행.",
                exc,
            )
            self.image_client = None

        # Instagram poster (Playwright-based)
        try:
            from src.instagram.browser_poster import BrowserPoster

            self.poster = BrowserPoster(headless=True)
            if not self.poster.login():
                logger.warning("Instagram 로그인 실패")
                self.poster = None
            else:
                logger.info("BrowserPoster 초기화 완료")
        except (ImportError, Exception) as exc:
            logger.warning(
                "BrowserPoster 사용 불가 ({}). 포스팅 없이 실행.",
                exc,
            )
            self.poster = None

        # Comment monitor (Playwright-based)
        if self.text_generator:
            try:
                from src.instagram.commenter import BrowserCommenter

                self.commenter = BrowserCommenter(
                    text_generator=self.text_generator,
                    headless=True,
                )
                logger.info("BrowserCommenter 초기화 완료")
            except (ImportError, Exception) as exc:
                logger.warning(
                    "BrowserCommenter 사용 불가 ({}). 댓글 모니터링 없이 실행.",
                    exc,
                )
                self.commenter = None
        else:
            logger.warning("TextGenerator 없음 — 댓글 모니터링 비활성화")
            self.commenter = None

        # Content planner & topic generator
        self.topic_generator = TopicGenerator(self.persona)
        self.content_planner = ContentPlanner(self.text_generator, self.persona)
        logger.info("ContentPlanner / TopicGenerator 초기화 완료")

    # ------------------------------------------------------------------
    # Schedule setup
    # ------------------------------------------------------------------

    def setup_schedules(self) -> None:
        """Configure APScheduler jobs based on ``schedule.yaml``."""
        self._scheduler = BlockingScheduler(timezone=self._tz)

        planning = self._schedule_cfg.get("planning", {}).get("weekly", {})
        posting = self._schedule_cfg.get("posting", {})
        comments = self._schedule_cfg.get("comments", {})

        # --- Weekly planning (cron) ---
        jitter_offset = random.randint(-self._jitter, self._jitter)
        plan_minute = (planning.get("minute", 0) + jitter_offset) % 60
        plan_hour = planning.get("hour", 6)
        plan_day = planning.get("day", "monday")[:3].lower()

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
            "스케줄: 주간 기획 {} {:02d}:{:02d} ({})",
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
                jitter=post_jitter * 60,
            ),
            id="posting_check",
            name="Posting Check",
            replace_existing=True,
        )
        logger.info(
            "스케줄: 포스팅 체크 {}분 간격 (지터 ±{}분)",
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
            "스케줄: 피크 댓글 체크 {}분, {}시-{}시 (지터 ±{}분)",
            comment_interval,
            peak_start,
            peak_end,
            comment_jitter,
        )

        # --- Comment monitoring: off-peak hours ---
        offpeak_interval = comments.get("off_peak_interval_minutes", 120)
        offpeak_jitter = random.randint(0, self._jitter)

        offpeak_hours = ",".join(
            str(h) for h in range(24) if h < peak_start or h >= peak_end
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
            "스케줄: 오프피크 댓글 체크 {}분 간격 (지터 ±{}분)",
            offpeak_interval,
            offpeak_jitter,
        )

        # --- Task queue processor (every 5 min) ---
        self._scheduler.add_job(
            self._safe_run(self._process_task_queue),
            IntervalTrigger(minutes=5, timezone=self._tz),
            id="task_queue_processor",
            name="Task Queue Processor",
            replace_existing=True,
        )
        logger.info("스케줄: 작업 큐 프로세서 5분 간격")

    # ------------------------------------------------------------------
    # Core cycles
    # ------------------------------------------------------------------

    def run_weekly_planning(self) -> None:
        """Generate and save the weekly content plan."""
        logger.info("=== 주간 콘텐츠 기획 시작 ===")

        if self.content_planner is None:
            logger.error("ContentPlanner 미초기화 — 기획 건너뜀")
            return

        plan = self.content_planner.generate_weekly_plan()
        self.content_planner.save_plan(plan)
        logger.info("주간 기획 저장 완료 ({}개 항목)", len(plan))

    def run_posting_cycle(self) -> None:
        """Check if a post should go out now, then generate and publish it."""
        logger.info("--- 포스팅 사이클 시작 ---")

        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_hour = now.hour

        # Reset daily counter
        if self._last_post_date != today_str:
            self._posts_today = 0
            self._last_post_date = today_str

        # Check daily limit
        max_posts = self._schedule_cfg.get("posting", {}).get(
            "max_posts_per_day", 2
        )
        if self._posts_today >= max_posts:
            logger.info(
                "일일 포스팅 제한 ({}/{})", self._posts_today, max_posts
            )
            return

        # Check optimal hours
        is_weekend = now.weekday() >= 5
        optimal_key = "weekend" if is_weekend else "weekday"
        optimal_hours: list[int] = self._schedule_cfg.get(
            "posting", {}
        ).get("optimal_hours", {}).get(optimal_key, [])
        if current_hour not in optimal_hours:
            logger.debug(
                "현재 {}시 — 최적 시간 {} 아님, 건너뜀",
                current_hour,
                optimal_hours,
            )
            return

        # Get content plan for today
        content: dict | None = None
        if self.content_planner:
            content = self.content_planner.get_todays_content()

        if content is None:
            logger.info("오늘 기획 없음 — 즉흥 주제 생성")
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

        logger.info("포스팅 주제: {}", content.get("topic", "unknown"))

        # Generate image
        image_path: str | None = None
        if self.image_client:
            try:
                scene = content.get("scene", "")
                image_prompt = (
                    self.persona.get_image_prompt(scene)
                    if self.persona
                    else scene
                )
                image_path = self.image_client.generate(image_prompt)
                logger.info("이미지 생성 완료: {}", image_path)
            except Exception as exc:
                logger.error("이미지 생성 실패: {}", exc)
                self.task_queue.add_task(
                    "retry_image",
                    {"content": content, "error": str(exc)},
                    priority=3,
                )
                return
        else:
            logger.warning("ImageClient 없음 — 이미지 생성 건너뜀")

        # Generate caption
        caption: str = ""
        if self.text_generator:
            try:
                topic = content["topic"]
                caption = self.text_generator.generate_caption(topic)
                logger.info("캡션 생성 완료 ({}자)", len(caption))
            except Exception as exc:
                logger.error("캡션 생성 실패: {}", exc)
                caption = ""

        # Append hashtags
        hashtags = content.get("hashtags", [])
        if not hashtags and self.topic_generator:
            hashtags = self.topic_generator.generate_hashtags(
                content["topic"]
            )
        if hashtags:
            tag_str = " ".join(hashtags)
            caption = f"{caption}\n\n{tag_str}" if caption else tag_str

        # Post to Instagram
        if self.poster and image_path:
            try:
                self.poster.post_photo(image_path, caption)
                self._posts_today += 1
                logger.info(
                    "포스팅 성공 ({}/{}): {}",
                    self._posts_today,
                    max_posts,
                    content["topic"],
                )
            except Exception as exc:
                logger.error("포스팅 실패: {}", exc)
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
                "포스팅 건너뜀 (poster={}, image={})",
                self.poster is not None,
                image_path,
            )

    def run_comment_cycle(self) -> None:
        """Check for unreplied comments, generate replies, and post them."""
        logger.info("--- 댓글 모니터링 사이클 시작 ---")

        if not self.commenter:
            logger.warning("BrowserCommenter 없음 — 댓글 사이클 건너뜀")
            return

        max_replies = self._schedule_cfg.get("comments", {}).get(
            "max_replies_per_check", 5
        )

        try:
            replied = self.commenter.auto_reply_recent(
                max_replies=max_replies,
                max_posts=5,
            )
            logger.info("댓글 사이클 완료: {}개 답글", replied)
        except Exception as exc:
            logger.error("댓글 사이클 실패: {}", exc)
            self.task_queue.add_task(
                "retry_comment", {"error": str(exc)}, priority=1
            )

    # ------------------------------------------------------------------
    # Task queue processing
    # ------------------------------------------------------------------

    def _process_task_queue(self) -> None:
        """Process pending tasks from the priority queue."""
        pending = self.task_queue.get_pending_count()
        if pending == 0:
            return

        logger.info("작업 큐 처리 (대기 {}건)", pending)

        task = self.task_queue.get_next()
        while task is not None:
            try:
                self._execute_task(task)
                self.task_queue.complete_task(task.id)
            except Exception as exc:
                logger.error("작업 {} 실패: {}", task.id, exc)
                self.task_queue.fail_task(task.id, str(exc))

            task = self.task_queue.get_next()

    def _execute_task(self, task: Task) -> None:
        """Execute a single task based on its type."""
        logger.info(
            "작업 실행: {} (type={}, priority={})",
            task.id,
            task.type,
            task.priority,
        )

        if task.type == "retry_post":
            self.run_posting_cycle()
        elif task.type == "retry_comment":
            self.run_comment_cycle()
        elif task.type in ("retry_reply", "retry_image"):
            pass  # Handled in next cycle
        else:
            logger.warning("알 수 없는 작업 타입: {}", task.type)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler loop."""
        logger.info("====== AI Influencer 오케스트레이터 시작 ======")
        logger.info("타임존: {}", self._tz)
        logger.info("지터: ±{}분", self._jitter)

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.setup_schedules()

        self._running = True
        logger.info("스케줄러 루프 시작...")

        try:
            if self._scheduler:
                self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self) -> None:
        """Gracefully shut down the scheduler and all components."""
        logger.info("====== 오케스트레이터 종료 중 ======")
        self._running = False

        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("APScheduler 종료")

        # Close browser components
        if self.commenter:
            try:
                self.commenter.close()
            except Exception:
                pass
        if self.poster:
            try:
                self.poster.close()
            except Exception:
                pass

        pending = self.task_queue.get_pending_count()
        if pending > 0:
            logger.warning("대기 중인 작업 {}건 남음", pending)

        logger.info("오케스트레이터 종료 완료")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle OS signals for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("시그널 {} 수신 — 종료 시작", sig_name)
        self.stop()

    # ------------------------------------------------------------------
    # Error-safe wrapper
    # ------------------------------------------------------------------

    def _safe_run(self, func: Any) -> Any:
        """Wrap a callable so that all exceptions are caught and logged."""

        def wrapper(*args: Any, **kwargs: Any) -> None:
            try:
                func(*args, **kwargs)
            except Exception:
                logger.error(
                    "{} 에서 에러 발생:\n{}",
                    func.__name__,
                    traceback.format_exc(),
                )

        wrapper.__name__ = func.__name__
        return wrapper
