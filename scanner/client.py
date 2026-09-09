"""Telethon client for the dedicated service account + FloodWait helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from core.config import Settings
from core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

# Anything above this many seconds is not worth sleeping through unattended.
MAX_FLOOD_SLEEP = 3600


def build_client(settings: Settings) -> TelegramClient:
    """The session file lives OUTSIDE the repo (TG_SESSION_PATH)."""
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise RuntimeError("TG_API_ID / TG_API_HASH .env faylda to'ldirilmagan")
    return TelegramClient(settings.tg_session_path, settings.tg_api_id, settings.tg_api_hash)


async def flood_safe(
    factory: Callable[[], Awaitable[T]],
    *,
    what: str,
    retries: int = 5,
    max_sleep: int = MAX_FLOOD_SLEEP,
    default: Any = None,
    reraise: bool = True,
) -> T | Any:
    """Await `factory()`, sleeping through FloodWaitError up to `retries` times."""
    for attempt in range(1, retries + 1):
        try:
            return await factory()
        except FloodWaitError as exc:
            wait = int(getattr(exc, "seconds", 0)) + 2
            if wait > max_sleep:
                log.error("flood_wait_too_long", what=what, seconds=wait)
                if reraise:
                    raise
                return default
            log.warning("flood_wait", what=what, seconds=wait, attempt=attempt)
            await asyncio.sleep(wait)
        except RPCError as exc:
            log.warning("rpc_error", what=what, error=str(exc))
            if reraise:
                raise
            return default
    log.error("flood_wait_giving_up", what=what)
    if reraise:
        raise RuntimeError(f"FloodWait retries exhausted for {what}")
    return default
