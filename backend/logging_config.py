"""Logging configuration for EVE Sentinel."""

import logging
import sys
from typing import Any


def setup_logging(level: str = "INFO") -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name, typically __name__

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class LoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    """Logger adapter that adds context to log messages."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Add extra context to log message."""
        extra = self.extra or {}
        context = " ".join(f"{k}={v}" for k, v in extra.items())
        if context:
            msg = f"{msg} | {context}"
        return msg, kwargs
