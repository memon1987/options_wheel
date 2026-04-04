"""Logging configuration for Options Wheel strategy."""

import os
import sys
import structlog
import logging
from pathlib import Path
from typing import Any, Dict


def _is_cloud_run() -> bool:
    """Detect if running in Cloud Run via the K_SERVICE env var."""
    return os.environ.get("K_SERVICE") is not None


def setup_logging(log_level: str = "INFO", log_to_file: bool = None, log_file: str = "logs/options_wheel.log") -> None:
    """Setup structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to file. Defaults to True for local dev,
                     False when running in Cloud Run.
        log_file: Log file path
    """
    # Default: log to file locally, log to stderr in Cloud Run
    if log_to_file is None:
        log_to_file = not _is_cloud_run()

    # Create logs directory if it doesn't exist
    if log_to_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

    # Configure standard library logging
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Remove any existing handlers to avoid duplicates
    root_logger.handlers.clear()

    formatter = logging.Formatter("%(message)s")
    if log_to_file:
        handler = logging.FileHandler(log_file, mode="a")
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

def get_logger(name: str) -> Any:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)
