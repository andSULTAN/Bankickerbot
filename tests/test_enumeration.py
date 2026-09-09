"""Participant enumeration against a fake Telethon client (no network)."""

from __future__ import annotations

from telethon.tl.types import User as TLUser

from scanner.enumeration import iter_participants, search_queries


def _user(user_id: int, *, bot: bool = False, deleted: bool = False) -> TLUser:
    return TLUser(id=user_id, bot=bot, deleted=deleted, first_name=f"U{user_id}")


class _FakeIterator:
    def __init__(self, users: list[TLUser]) -> None:
        self._users = list(users)

    def __aiter__(self):
        return self

    async def __anext__(self) -> TLUser:
        if not self._users:
            raise StopAsyncIteration
        return self._users.pop(0)


class FakeClient:
    """Records how `iter_participants` was called and replays canned users."""

    def __init__(self, users: list[TLUser]) -> None:
        self.users = users
        self.searches: list[object] = []

    def iter_participants(self, entity, search=None):
        self.searches.append(search)
        return _FakeIterator(self.users)


async def test_search_is_always_a_string():
    """Telethon serializes `search` directly: None raises a TypeError deep in
    the MTProto layer, so the plain sweep must send an empty string."""
    client = FakeClient([_user(1), _user(2)])

    seen = [user.id async for user in iter_participants(client, object())]

    assert seen == [1, 2]
    assert client.searches == [""]
    assert not any(search is None for search in client.searches)


async def test_bots_and_deleted_accounts_are_skipped():
    client = FakeClient([_user(1), _user(2, bot=True), _user(3, deleted=True), _user(1)])

    seen = [user.id async for user in iter_participants(client, object())]

    assert seen == [1]  # bot and deleted dropped, duplicate id yielded once


async def test_done_queries_are_reported():
    client = FakeClient([_user(7)])
    finished: list[tuple[str, int]] = []

    async for _ in iter_participants(
        client, object(), on_query_done=lambda query, count: finished.append((query, count))
    ):
        pass

    assert finished == [("", 1)]


def test_search_queries_are_unique_and_start_with_the_plain_sweep():
    queries = search_queries()
    assert queries[0] == ""
    assert len(queries) == len(set(queries))
