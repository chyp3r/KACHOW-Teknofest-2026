"""Shared pytest fixtures.

Did not exist anywhere in the repo before this: every existing test hand-rolled
its own mocks, which is why the same ``MagicMock(spec=BaseLLMClient)`` pattern
is duplicated across dozens of files. New tests should use these instead.
"""

import asyncio
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.llms.base import BaseLLMClient


class FakeLLMClient(BaseLLMClient):
    """A configurable stand-in for a real LLM client.

    Unlike a bare ``MagicMock(spec=BaseLLMClient)``, this is a real
    (sub)class instance, so ``isinstance`` checks and agent constructors that
    inspect the client's type keep working. Configure return values by
    setting ``.generate_return``, ``.generate_structured_return`` (or
    ``.generate_structured_side_effect`` for a callable/exception sequence),
    and ``.stream_chunks``.
    """

    def __init__(self) -> None:
        self.generate_return: str = ""
        self.generate_structured_return: Any = None
        self.generate_structured_side_effect: Optional[list[Any]] = None
        self.stream_chunks: list[str] = []
        self.generate_calls: list[dict] = []
        self.generate_structured_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def generate(self, messages, temperature=None, max_tokens=None, **kwargs) -> str:
        self.generate_calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens, **kwargs}
        )
        return self.generate_return

    async def generate_structured(self, messages, response_model, temperature=None, **kwargs) -> Any:
        self.generate_structured_calls.append(
            {"messages": messages, "response_model": response_model, "temperature": temperature, **kwargs}
        )
        if self.generate_structured_side_effect is not None:
            outcome = self.generate_structured_side_effect.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return self.generate_structured_return

    def stream(self, messages, temperature=None, max_tokens=None, **kwargs) -> AsyncIterator[str]:
        self.stream_calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens, **kwargs}
        )

        async def _gen():
            for chunk in self.stream_chunks:
                yield chunk

        return _gen()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    """A quality-tier fake client."""
    return FakeLLMClient()


@pytest.fixture
def fake_fast_llm() -> FakeLLMClient:
    """A fast-tier fake client, kept as a separate instance from fake_llm so
    a test can assert which tier a given call went through."""
    return FakeLLMClient()


@pytest.fixture
def queue_config() -> dict:
    """A LangGraph config carrying a fresh asyncio.Queue as the SSE progress channel."""
    return {"configurable": {"status_queue": asyncio.Queue()}}


async def drain_events(queue: "asyncio.Queue") -> list[dict]:
    """Collect every event currently buffered in a progress queue.

    Args:
        queue: The queue a graph run's config was given.

    Returns:
        Every event published so far, in order. Does not block waiting for
        more -- call it after the run under test has completed.
    """
    events = []
    while not queue.empty():
        events.append(await queue.get())
    return events


@pytest.fixture
def tmp_storage_dir(tmp_path, monkeypatch):
    """Point settings.LOCAL_STORAGE_DIR at a throwaway directory.

    Several existing tests wrote into the real local storage directory
    because nothing isolated them from it. New tests should request this
    fixture instead.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_checkpointer(monkeypatch):
    """Force get_checkpointer() to return None for the duration of a test."""
    from app.infrastructure import checkpointing

    monkeypatch.setattr(checkpointing, "get_checkpointer", lambda: None)
    monkeypatch.setattr(checkpointing.postgres, "get_checkpointer", lambda: None)
    return None


@pytest.fixture(autouse=True)
def _reset_redis_cache_between_tests():
    """Drop the process-wide Redis client reference after every test.

    pytest-asyncio gives each test its own event loop by default, and a
    sync TestClient-based test runs its request through yet another,
    short-lived anyio-portal loop that is already closed by the time this
    teardown runs -- but app.infrastructure.cache.get_cache() is a lazy
    process-wide singleton whose connection binds to whichever loop first
    called connect(). Reusing it from a later test's loop raises "attached
    to a different loop" (surfaced via any endpoint behind rate_limit()),
    and *closing* it here doesn't help either: gracefully closing a socket
    requires the loop it was opened on, which is already gone, so an
    attempted close just trades that error for "Event loop is closed".

    Dropping the reference (not closing it) is the deliberate fix: the OS
    reclaims the abandoned socket, and the next get_cache() call builds a
    fresh RedisCache bound to whatever loop is current at that point.
    """
    yield
    from app.infrastructure import cache as cache_module

    cache_module._cache = None
