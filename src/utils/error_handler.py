"""
Error handling utilities for the AI Influencer project.

Provides custom exception classes, a retry decorator backed by tenacity,
an Instagram-block handler, and an ``ErrorClassifier`` that inspects
exceptions to decide on the appropriate recovery action.
"""

from __future__ import annotations

import enum
import time
from functools import wraps
from typing import Callable, TypeVar

from loguru import logger
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class InstagramError(Exception):
    """Base exception for all Instagram-related errors."""


class RateLimitError(InstagramError):
    """Raised when the Instagram API returns a rate-limit / throttle signal."""


class ContentFilterError(InstagramError):
    """Raised when content is rejected by Instagram's content filters."""


class PersonaViolationError(Exception):
    """Raised when generated content violates the configured persona rules."""


class AuthenticationError(InstagramError):
    """Raised when Instagram session or credentials are invalid."""


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable)

_RETRYABLE_EXCEPTIONS = (
    InstagramError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry_with_backoff(
    max_retries: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    retryable_exceptions: tuple[type[BaseException], ...] = _RETRYABLE_EXCEPTIONS,
) -> Callable[[F], F]:
    """Decorator that retries the wrapped function with exponential backoff.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts (default 3).
    min_wait:
        Minimum backoff delay in seconds (default 1).
    max_wait:
        Maximum backoff delay in seconds (default 30).
    retryable_exceptions:
        Exception types eligible for retry.  Defaults to Instagram and
        network-related errors.  ``AuthenticationError`` is deliberately
        included (inherits from ``InstagramError``) so callers that need
        to exclude it can pass a custom tuple.

    Returns
    -------
    Callable
        Decorated function with retry logic.
    """

    def decorator(func: F) -> F:
        @retry(
            stop=stop_after_attempt(max_retries + 1),  # +1 because attempt 1 is the first try
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type(retryable_exceptions),
            reraise=True,
            before_sleep=lambda retry_state: logger.warning(
                "Retry {attempt}/{max} for {fn} after {exc}",
                attempt=retry_state.attempt_number,
                max=max_retries,
                fn=retry_state.fn.__name__ if retry_state.fn else "unknown",
                exc=retry_state.outcome.exception() if retry_state.outcome else "unknown",
            ),
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Instagram block handler
# ---------------------------------------------------------------------------

_BLOCK_SLEEP_SECONDS: int = 6 * 60 * 60  # 6 hours


def handle_instagram_block(
    reason: str = "Unknown",
    sleep_seconds: int = _BLOCK_SLEEP_SECONDS,
) -> None:
    """Log a block event and sleep for *sleep_seconds* (default 6 hours).

    This is a blocking call intended to be invoked when Instagram signals
    that the account has been temporarily restricted.

    Parameters
    ----------
    reason:
        Human-readable description of why the block was triggered.
    sleep_seconds:
        How long to sleep (seconds).  Default is 21 600 (6 hours).
    """
    logger.critical(
        "Instagram block detected – reason: {reason}. "
        "Sleeping for {hours:.1f} hours ({seconds} seconds).",
        reason=reason,
        hours=sleep_seconds / 3600,
        seconds=sleep_seconds,
    )
    time.sleep(sleep_seconds)
    logger.info("Resuming after Instagram block cooldown.")


# ---------------------------------------------------------------------------
# Error classifier
# ---------------------------------------------------------------------------


class RecoveryAction(enum.Enum):
    """Actions the caller can take based on error classification."""

    RETRY = "retry"
    RATE_LIMIT_WAIT = "rate_limit_wait"
    BLOCK_SLEEP = "block_sleep"
    REAUTHENTICATE = "reauthenticate"
    REGENERATE_CONTENT = "regenerate_content"
    SKIP = "skip"
    ABORT = "abort"


class ErrorClassifier:
    """Inspects an exception and decides the appropriate recovery action.

    Usage::

        classifier = ErrorClassifier()
        action = classifier.classify(exc)
        if action == RecoveryAction.BLOCK_SLEEP:
            handle_instagram_block(reason=str(exc))
    """

    # Instagram error substrings that hint at specific conditions
    _BLOCK_KEYWORDS = (
        "blocked",
        "action blocked",
        "temporarily banned",
        "please wait",
        "challenge_required",
    )
    _RATE_LIMIT_KEYWORDS = (
        "rate limit",
        "throttled",
        "too many requests",
        "please wait a few minutes",
        "429",
    )
    _AUTH_KEYWORDS = (
        "login_required",
        "not authorized",
        "invalid session",
        "checkpoint_required",
    )

    def classify(self, exc: BaseException) -> RecoveryAction:
        """Return the recommended ``RecoveryAction`` for *exc*.

        The method inspects the exception type first.  For generic
        ``InstagramError`` instances it falls back to keyword matching
        on the stringified message.
        """
        # Exact-type checks (most specific first)
        if isinstance(exc, AuthenticationError):
            return RecoveryAction.REAUTHENTICATE

        if isinstance(exc, RateLimitError):
            return RecoveryAction.RATE_LIMIT_WAIT

        if isinstance(exc, ContentFilterError):
            return RecoveryAction.REGENERATE_CONTENT

        if isinstance(exc, PersonaViolationError):
            return RecoveryAction.REGENERATE_CONTENT

        # Generic InstagramError – inspect message
        if isinstance(exc, InstagramError):
            return self._classify_by_message(str(exc))

        # Network / transient errors
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            return RecoveryAction.RETRY

        # Anything else is unrecoverable
        return RecoveryAction.ABORT

    def _classify_by_message(self, message: str) -> RecoveryAction:
        """Heuristic classification based on error message content."""
        lower = message.lower()

        if any(kw in lower for kw in self._BLOCK_KEYWORDS):
            return RecoveryAction.BLOCK_SLEEP

        if any(kw in lower for kw in self._RATE_LIMIT_KEYWORDS):
            return RecoveryAction.RATE_LIMIT_WAIT

        if any(kw in lower for kw in self._AUTH_KEYWORDS):
            return RecoveryAction.REAUTHENTICATE

        # Default for unrecognised Instagram errors: retry once, then skip
        return RecoveryAction.RETRY

    @staticmethod
    def describe(action: RecoveryAction) -> str:
        """Return a human-readable description of *action*."""
        descriptions = {
            RecoveryAction.RETRY: "Retry the operation with backoff.",
            RecoveryAction.RATE_LIMIT_WAIT: "Wait for the rate-limit window to reset.",
            RecoveryAction.BLOCK_SLEEP: "Account blocked; sleep for several hours.",
            RecoveryAction.REAUTHENTICATE: "Session expired; re-authenticate.",
            RecoveryAction.REGENERATE_CONTENT: "Content rejected; regenerate.",
            RecoveryAction.SKIP: "Skip this item and continue.",
            RecoveryAction.ABORT: "Unrecoverable error; abort.",
        }
        return descriptions.get(action, "Unknown action.")
