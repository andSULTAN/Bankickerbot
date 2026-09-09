"""JSON logging to stdout for both components."""

from __future__ import annotations

import logging
import sys

import structlog

# Third-party loggers that are far too chatty at INFO (Telethon reports every
# downloaded chunk). They are only silenced below DEBUG.
NOISY_LOGGERS = ("telethon", "asyncio", "PIL", "aiosqlite", "httpx")


def setup_logging(level: str = "INFO", *, pretty: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    if level.upper() != "DEBUG":
        for name in NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
    renderer = (
        structlog.dev.ConsoleRenderer() if pretty else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
