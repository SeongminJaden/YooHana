"""
Priority-based task queue for the AI Influencer scheduler.

Provides a thread-safe in-memory queue with priority ordering so that
urgent tasks (e.g. reply to a comment) are processed before low-priority
background work (e.g. analytics).

Priority levels
---------------
- 1  = urgent  (reply to comment)
- 5  = normal  (scheduled post)
- 10 = low     (analytics, cleanup)
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.utils.logger import get_logger

logger = get_logger()


# Priority constants for readability
PRIORITY_URGENT: int = 1
PRIORITY_NORMAL: int = 5
PRIORITY_LOW: int = 10


@dataclass(order=True)
class Task:
    """A single unit of work in the task queue.

    The ``order=True`` on the dataclass uses ``priority`` (then
    ``created_at``) for comparison, so lower priority numbers are
    processed first.

    Attributes
    ----------
    priority : int
        Numeric priority (1 = urgent, 5 = normal, 10 = low).
    created_at : str
        ISO-8601 timestamp of when the task was created.
    id : str
        Unique task identifier (UUID4).
    type : str
        Task category (e.g. ``"scheduled_post"``, ``"reply_comment"``).
    payload : dict
        Arbitrary data the executor needs to complete the task.
    status : str
        One of ``"pending"``, ``"in_progress"``, ``"completed"``, ``"failed"``.
    error : str | None
        Error message if the task failed.
    """

    priority: int = field(default=PRIORITY_NORMAL)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12], compare=False)
    type: str = field(default="", compare=False)
    payload: dict = field(default_factory=dict, compare=False)
    status: str = field(default="pending", compare=False)
    error: str | None = field(default=None, compare=False)


class TaskQueue:
    """Thread-safe priority queue for scheduling tasks.

    Tasks with lower ``priority`` values are returned first by
    ``get_next()``.  Within the same priority, earlier ``created_at``
    wins.

    Examples
    --------
    >>> q = TaskQueue()
    >>> q.add_task("reply_comment", {"comment_id": "abc"}, priority=1)
    >>> q.add_task("scheduled_post", {"topic": "카페"}, priority=5)
    >>> task = q.get_next()
    >>> task.type
    'reply_comment'
    """

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = PRIORITY_NORMAL,
    ) -> str:
        """Add a new task to the queue.

        Parameters
        ----------
        task_type : str
            Category of the task (e.g. ``"scheduled_post"``).
        payload : dict | None
            Data needed to execute the task.
        priority : int
            Priority level (1=urgent, 5=normal, 10=low).

        Returns
        -------
        str
            The unique task id.
        """
        task = Task(
            type=task_type,
            payload=payload or {},
            priority=priority,
        )

        with self._lock:
            self._tasks.append(task)
            self._tasks.sort()  # maintain priority order

        logger.debug(
            "Task added: id={} type={} priority={}",
            task.id,
            task.type,
            task.priority,
        )
        return task.id

    def get_next(self) -> Task | None:
        """Return the highest-priority pending task, or *None*.

        The task's status is set to ``"in_progress"`` before returning.

        Returns
        -------
        Task | None
            The next task to process, or *None* if the queue has no
            pending tasks.
        """
        with self._lock:
            for task in self._tasks:
                if task.status == "pending":
                    task.status = "in_progress"
                    logger.debug(
                        "Task dequeued: id={} type={} priority={}",
                        task.id,
                        task.type,
                        task.priority,
                    )
                    return task

        return None

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed.

        Parameters
        ----------
        task_id : str
            The unique task identifier.
        """
        with self._lock:
            task = self._find_task(task_id)
            if task:
                task.status = "completed"
                logger.debug("Task completed: id={} type={}", task.id, task.type)
            else:
                logger.warning("Task not found for completion: {}", task_id)

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed and record the error message.

        Parameters
        ----------
        task_id : str
            The unique task identifier.
        error : str
            Human-readable error description.
        """
        with self._lock:
            task = self._find_task(task_id)
            if task:
                task.status = "failed"
                task.error = error
                logger.warning(
                    "Task failed: id={} type={} error={}",
                    task.id,
                    task.type,
                    error,
                )
            else:
                logger.warning("Task not found for failure: {}", task_id)

    def get_pending_count(self) -> int:
        """Return the number of tasks with ``"pending"`` status.

        Returns
        -------
        int
            Count of pending tasks.
        """
        with self._lock:
            return sum(1 for t in self._tasks if t.status == "pending")

    # ------------------------------------------------------------------
    # Convenience / introspection
    # ------------------------------------------------------------------

    def get_all_tasks(self) -> list[Task]:
        """Return a shallow copy of the full task list (all statuses)."""
        with self._lock:
            return list(self._tasks)

    def get_failed_tasks(self) -> list[Task]:
        """Return all tasks with ``"failed"`` status."""
        with self._lock:
            return [t for t in self._tasks if t.status == "failed"]

    def clear_completed(self) -> int:
        """Remove all completed and failed tasks from the queue.

        Returns
        -------
        int
            Number of tasks removed.
        """
        with self._lock:
            before = len(self._tasks)
            self._tasks = [
                t for t in self._tasks if t.status in ("pending", "in_progress")
            ]
            removed = before - len(self._tasks)

        if removed:
            logger.debug("Cleared {} completed/failed tasks", removed)
        return removed

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)

    def __repr__(self) -> str:
        return (
            f"TaskQueue(total={len(self)}, "
            f"pending={self.get_pending_count()})"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_task(self, task_id: str) -> Task | None:
        """Find a task by id (caller must hold ``self._lock``)."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None
