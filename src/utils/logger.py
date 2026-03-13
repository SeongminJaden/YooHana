"""
Loguru-based logging utility for the AI Influencer project.

Provides a pre-configured logger that writes to both console and file
with rotation, retention, and a consistent format across all modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

# Project root: two levels up from this file (src/utils/logger.py -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "outputs" / "logs"

# Unified log format: timestamp | level | module | message
_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level:<8}</level> | "
    "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level:<8} | "
    "{module}:{function}:{line} | "
    "{message}"
)

_configured = False


def _configure_logger(
    log_dir: Path = _DEFAULT_LOG_DIR,
    rotation: str = "10 MB",
    retention: str = "30 days",
    console_level: str = "DEBUG",
    file_level: str = "DEBUG",
) -> None:
    """Configure loguru sinks for console and file output.

    Called once on first ``get_logger()`` invocation.  Subsequent calls
    are no-ops so sinks are never duplicated.
    """
    global _configured
    if _configured:
        return

    # Remove the default stderr sink so we can replace it with our own format.
    logger.remove()

    # --- Console sink ---
    logger.add(
        sys.stderr,
        format=_LOG_FORMAT,
        level=console_level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # --- File sink ---
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ai_influencer_{time:YYYY-MM-DD}.log"

    logger.add(
        str(log_file),
        format=_FILE_FORMAT,
        level=file_level,
        rotation=rotation,
        retention=retention,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    # --- Error-only file for quick triage ---
    error_file = log_dir / "errors_{time:YYYY-MM-DD}.log"
    logger.add(
        str(error_file),
        format=_FILE_FORMAT,
        level="ERROR",
        rotation=rotation,
        retention=retention,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )

    _configured = True
    logger.debug("Logger initialised – log directory: {}", log_dir)


def get_logger(
    log_dir: Path | str | None = None,
    console_level: str = "DEBUG",
    file_level: str = "DEBUG",
) -> logger.__class__:
    """Return the project-wide loguru logger, configuring it on first call.

    Parameters
    ----------
    log_dir:
        Directory for log files.  Defaults to ``<project_root>/outputs/logs/``.
    console_level:
        Minimum level for console output.
    file_level:
        Minimum level for file output.

    Returns
    -------
    loguru.Logger
        The configured loguru logger instance.
    """
    resolved_dir = Path(log_dir) if log_dir is not None else _DEFAULT_LOG_DIR
    _configure_logger(
        log_dir=resolved_dir,
        console_level=console_level,
        file_level=file_level,
    )
    return logger
