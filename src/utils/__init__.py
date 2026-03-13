"""Utility modules for the AI Influencer project."""

from src.utils.error_handler import (
    AuthenticationError,
    ContentFilterError,
    ErrorClassifier,
    InstagramError,
    PersonaViolationError,
    RateLimitError,
    RecoveryAction,
    handle_instagram_block,
    retry_with_backoff,
)
from src.utils.logger import get_logger
from src.utils.rate_limiter import RateLimiter

__all__ = [
    # Logger
    "get_logger",
    # Rate limiter
    "RateLimiter",
    # Exceptions
    "InstagramError",
    "RateLimitError",
    "ContentFilterError",
    "PersonaViolationError",
    "AuthenticationError",
    # Error handling
    "retry_with_backoff",
    "handle_instagram_block",
    "ErrorClassifier",
    "RecoveryAction",
]
