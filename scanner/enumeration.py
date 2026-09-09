"""Participant enumeration with the standard >10k fallback.

Telegram caps `channels.getParticipants` at roughly 10 000 results per query, so
for bigger chats we run many *search* queries (letters, digits, common bigrams)
and deduplicate. That still is not a guarantee, hence `EnumerationReport.capped`,
which the CLI reports back to the operator.
"""

from __future__ import annotations

import string
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.tl.types import User

from core.logging import get_logger
from scanner.client import flood_safe

log = get_logger(__name__)

# ~10k is the documented server-side cap for a single participants query.
PARTICIPANTS_CAP = 10_000

LATIN = string.ascii_lowercase
DIGITS = string.digits
CYRILLIC = "абвгдеёжзийклмнопрстуфхцчшщыэюя"
UZBEK_EXTRA = "oʻgʻ"


def search_queries() -> list[str]:
    """Queries used for the fallback sweep, most productive first."""
    queries = [""]
    queries += list(LATIN)
    queries += list(CYRILLIC)
    queries += list(DIGITS)
    queries += [a + b for a in "aeiou" for b in LATIN]
    seen: set[str] = set()
    unique = []
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


@dataclass
class EnumerationReport:
    total: int = 0
    capped: bool = False
    queries_used: list[str] = field(default_factory=list)


async def iter_participants(
    client: TelegramClient,
    entity,
    *,
    done_queries: set[str] | None = None,
    on_query_done: Callable[[str, int], None] | None = None,
    report: EnumerationReport | None = None,
) -> AsyncIterator[User]:
    """Yield every participant exactly once (resumable via `done_queries`)."""
    done = set(done_queries or ())
    seen: set[int] = set()
    report = report or EnumerationReport()

    # First pass: plain enumeration. Enough for chats below the cap.
    if "" not in done:
        count = 0
        async for user in _iter_query(client, entity, ""):
            if user.id in seen:
                continue
            seen.add(user.id)
            count += 1
            yield user
        report.queries_used.append("")
        if on_query_done:
            on_query_done("", count)
        if count < PARTICIPANTS_CAP:
            report.total = len(seen)
            return
        report.capped = True
        log.warning("participants_cap_hit", count=count, hint="search fallback boshlanmoqda")
    else:
        report.capped = True

    for query in search_queries():
        if not query or query in done:
            continue
        count = 0
        async for user in _iter_query(client, entity, query):
            if user.id in seen:
                continue
            seen.add(user.id)
            count += 1
            yield user
        report.queries_used.append(query)
        if on_query_done:
            on_query_done(query, count)

    report.total = len(seen)


async def _iter_query(client: TelegramClient, entity, query: str) -> AsyncIterator[User]:
    """One `iter_participants` sweep, tolerant to FloodWait."""
    iterator = client.iter_participants(entity, search=query or None)
    while True:
        try:
            user = await flood_safe(
                iterator.__anext__,
                what=f"iter_participants(search={query!r})",
                reraise=False,
                default=StopAsyncIteration,
            )
        except StopAsyncIteration:
            return
        if user is StopAsyncIteration or user is None:
            return
        if isinstance(user, User) and not user.bot and not user.deleted:
            yield user
