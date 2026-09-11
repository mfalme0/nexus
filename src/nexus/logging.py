"""Structured logging configuration using structlog."""

import logging
import sys
from typing import Any

import structlog

from nexus.config import settings


def configure_logging() -> None:
    """Configure structlog with console rendering and log level from settings."""
    log_level = getattr(logging, settings.log_level.upper(), logging.DEBUG)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if settings.env.value == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a bound logger instance."""
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()
