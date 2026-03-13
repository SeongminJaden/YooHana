"""
Thread-safe, synchronous API rate limiter for the AI Influencer project.

Tracks how many calls have been made within a rolling time window for each
action type (comments, likes, posts) and blocks until a slot is available.
Limits are loaded from ``config/settings.yaml`` under ``instagram.rate_limits``.
A random jitter delay is injected between ``delay_min`` and ``delay_max`` to
mimic human behaviour.
"""

from __future__ import annotations

import random
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SETTINGS = _PROJECT_ROOT / "config" / "settings.yaml"


@dataclass(frozen=True)
class ActionLimit:
    """Describes the rate constraint for a single action type."""

    max_calls: int
    window_seconds: float  # rolling window length


@dataclass
class _ActionState:
    """Mutable state for tracking calls within a window."""

    timestamps: deque[float] = field(default_factory=deque)
    lock: threading.Lock = field(default_factory=threading.Lock)


class RateLimiter:
    """Synchronous, thread-safe rate limiter.

    Parameters
    ----------
    settings_path:
        Path to ``settings.yaml``.  When *None*, falls back to default.
    limits_override:
        Dict mapping action names to ``ActionLimit`` instances.  When
        provided, ``settings_path`` is ignored.
    """

    def __init__(
        self,
        settings_path: str | Path | None = None,
        limits_override: dict[str, ActionLimit] | None = None,
    ) -> None:
        if limits_override is not None:
            self._limits = dict(limits_override)
        else:
            self._limits = self._load_limits(settings_path or _DEFAULT_SETTINGS)

        self._delay_min: float = 2.0
        self._delay_max: float = 5.0
        self._states: dict[str, _ActionState] = defaultdict(_ActionState)

        # Try loading delay bounds from config
        if limits_override is None:
            self._load_delays(settings_path or _DEFAULT_SETTINGS)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_limits(self, path: str | Path) -> dict[str, ActionLimit]:
        """Parse ``instagram.rate_limits`` from *path* into ActionLimit map."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Settings file not found: {path}")

        with open(path, "r", encoding="utf-8") as fh:
            cfg: dict[str, Any] = yaml.safe_load(fh)

        rl_cfg = cfg.get("instagram", {}).get("rate_limits", {})

        limits: dict[str, ActionLimit] = {}

        # comments_per_hour -> action="comments", window=3600s
        if "comments_per_hour" in rl_cfg:
            limits["comments"] = ActionLimit(
                max_calls=int(rl_cfg["comments_per_hour"]),
                window_seconds=3600.0,
            )
        # likes_per_hour -> action="likes", window=3600s
        if "likes_per_hour" in rl_cfg:
            limits["likes"] = ActionLimit(
                max_calls=int(rl_cfg["likes_per_hour"]),
                window_seconds=3600.0,
            )
        # posts_per_day -> action="posts", window=86400s
        if "posts_per_day" in rl_cfg:
            limits["posts"] = ActionLimit(
                max_calls=int(rl_cfg["posts_per_day"]),
                window_seconds=86400.0,
            )

        if not limits:
            raise ValueError(
                f"No rate limits found in {path} under instagram.rate_limits"
            )

        return limits

    def _load_delays(self, path: str | Path) -> None:
        """Load delay_min / delay_max from settings."""
        path = Path(path)
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as fh:
            cfg: dict[str, Any] = yaml.safe_load(fh)
        rl_cfg = cfg.get("instagram", {}).get("rate_limits", {})
        self._delay_min = float(rl_cfg.get("delay_min", self._delay_min))
        self._delay_max = float(rl_cfg.get("delay_max", self._delay_max))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def registered_actions(self) -> list[str]:
        """Return the names of all registered action types."""
        return list(self._limits.keys())

    def wait(self, action: str) -> float:
        """Block until *action* is allowed, then record the call.

        Returns the total seconds spent waiting (jitter + rate-limit wait).
        """
        if action not in self._limits:
            raise KeyError(
                f"Unknown action '{action}'. "
                f"Registered actions: {self.registered_actions}"
            )

        limit = self._limits[action]
        state = self._states[action]
        waited = 0.0

        with state.lock:
            waited += self._enforce_window(state, limit)
            state.timestamps.append(time.monotonic())

        # Random jitter to look human
        jitter = random.uniform(self._delay_min, self._delay_max)
        time.sleep(jitter)
        waited += jitter

        return waited

    def remaining(self, action: str) -> int:
        """Return how many calls are still available in the current window."""
        if action not in self._limits:
            raise KeyError(f"Unknown action '{action}'.")

        limit = self._limits[action]
        state = self._states[action]

        with state.lock:
            self._purge_expired(state, limit)
            return max(0, limit.max_calls - len(state.timestamps))

    def reset(self, action: str | None = None) -> None:
        """Clear recorded timestamps for *action* (or all actions)."""
        if action is not None:
            if action in self._states:
                with self._states[action].lock:
                    self._states[action].timestamps.clear()
        else:
            for state in self._states.values():
                with state.lock:
                    state.timestamps.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _purge_expired(state: _ActionState, limit: ActionLimit) -> None:
        """Remove timestamps that have fallen outside the rolling window."""
        cutoff = time.monotonic() - limit.window_seconds
        while state.timestamps and state.timestamps[0] < cutoff:
            state.timestamps.popleft()

    def _enforce_window(self, state: _ActionState, limit: ActionLimit) -> float:
        """Wait until a slot opens in the window.  Returns seconds waited."""
        total_waited = 0.0
        while True:
            self._purge_expired(state, limit)
            if len(state.timestamps) < limit.max_calls:
                return total_waited
            # Must wait until the oldest timestamp expires
            sleep_for = (
                state.timestamps[0] + limit.window_seconds - time.monotonic()
            )
            if sleep_for > 0:
                # Release the lock while sleeping so other actions aren't blocked
                state.lock.release()
                try:
                    time.sleep(sleep_for + 0.05)  # small buffer
                    total_waited += sleep_for + 0.05
                finally:
                    state.lock.acquire()
