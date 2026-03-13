"""Tests for scheduler module."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.scheduler.task_queue import TaskQueue, PRIORITY_URGENT, PRIORITY_NORMAL, PRIORITY_LOW


class TestTaskQueue:
    def setup_method(self):
        self.queue = TaskQueue()

    def test_add_and_get_task(self):
        task_id = self.queue.add_task("post", {"topic": "카페"})
        assert task_id is not None

        task = self.queue.get_next()
        assert task is not None
        assert task.type == "post"
        assert task.payload["topic"] == "카페"
        assert task.status == "in_progress"

    def test_priority_ordering(self):
        self.queue.add_task("low", {}, priority=PRIORITY_LOW)
        self.queue.add_task("urgent", {}, priority=PRIORITY_URGENT)
        self.queue.add_task("normal", {}, priority=PRIORITY_NORMAL)

        task1 = self.queue.get_next()
        assert task1.type == "urgent"

        task2 = self.queue.get_next()
        assert task2.type == "normal"

        task3 = self.queue.get_next()
        assert task3.type == "low"

    def test_complete_task(self):
        task_id = self.queue.add_task("test", {})
        task = self.queue.get_next()
        self.queue.complete_task(task_id)

        assert self.queue.get_pending_count() == 0

    def test_fail_task(self):
        task_id = self.queue.add_task("test", {})
        self.queue.get_next()
        self.queue.fail_task(task_id, "test error")

        failed = self.queue.get_failed_tasks()
        assert len(failed) == 1
        assert failed[0].error == "test error"

    def test_empty_queue_returns_none(self):
        task = self.queue.get_next()
        assert task is None

    def test_pending_count(self):
        self.queue.add_task("a", {})
        self.queue.add_task("b", {})
        self.queue.add_task("c", {})
        assert self.queue.get_pending_count() == 3

        self.queue.get_next()
        assert self.queue.get_pending_count() == 2
