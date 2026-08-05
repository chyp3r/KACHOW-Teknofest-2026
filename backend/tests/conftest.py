"""Shared pytest fixtures.

Did not exist anywhere in the repo before this: every existing test hand-rolled
its own mocks, which is why the same ``MagicMock(spec=BaseLLMClient)`` pattern
is duplicated across dozens of files. New tests should use these instead.
"""

import asyncio
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock

import zlib

import pytest

from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.llms.base import BaseLLMClient, ToolCallResponse


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
        self.generate_with_tools_side_effect: Optional[list[ToolCallResponse]] = None
        self.generate_with_tools_return: ToolCallResponse = ToolCallResponse()
        self.generate_calls: list[dict] = []
        self.generate_structured_calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.generate_with_tools_calls: list[dict] = []

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

    async def generate_with_tools(
        self, messages, tools, temperature=None, max_tokens=None, **kwargs
    ) -> ToolCallResponse:
        self.generate_with_tools_calls.append(
            {"messages": messages, "tools": tools, "temperature": temperature, "max_tokens": max_tokens, **kwargs}
        )
        if self.generate_with_tools_side_effect is not None:
            outcome = self.generate_with_tools_side_effect.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return self.generate_with_tools_return


class FakeEmbeddingsClient(BaseEmbeddingsClient):
    """A deterministic stand-in for a real embeddings client.

    Same rationale as ``FakeLLMClient``: a real subclass rather than a
    ``MagicMock``, so ``isinstance`` checks and constructors that inspect the
    client keep working.

    Vectors are derived from the text itself so a test can assert *which* text
    is closest to which prototype without hardcoding an embedding. Configure
    ``vectors`` to map exact strings to exact vectors; anything unmapped falls
    back to a deterministic hash-derived vector, which is near-orthogonal to
    everything else and therefore reads as "no semantic match" -- the right
    default for a test that only cares that some other text *did* match.
    """

    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension
        self.vectors: dict[str, list[float]] = {}
        self.embed_query_calls: list[str] = []
        self.embed_documents_calls: list[list[str]] = []
        self.raise_on_query: Exception | None = None

    def _vector_for(self, text: str) -> list[float]:
        if text in self.vectors:
            return list(self.vectors[text])
        seed = zlib.crc32(text.encode("utf-8"))
        return [((seed >> (index * 3)) & 0xFF) / 255.0 for index in range(self.dimension)]

    async def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls.append(text)
        if self.raise_on_query is not None:
            raise self.raise_on_query
        return self._vector_for(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls.append(list(texts))
        return [self._vector_for(text) for text in texts]


@pytest.fixture
def fake_embeddings() -> FakeEmbeddingsClient:
    """A deterministic embeddings client for the semantic decision layer."""
    return FakeEmbeddingsClient()


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
def _default_require_auth_off(monkeypatch):
    """Default settings.REQUIRE_AUTH to False for every test.

    REQUIRE_AUTH now defaults to True in the application itself (Faz 4 RBAC
    -- production must not silently run unauthenticated). Most existing API
    tests predate that and exercise endpoint logic through the TestClient
    with no Authorization header and no dependency override for
    get_current_user/require_auth_if_enabled -- under the new default those
    would 401 before ever reaching the handler under test. Mirrors
    `_disable_run_recording` immediately below: real/new behaviour off by
    default, opted back into explicitly by the handful of tests
    (test_lifespan.py, and any test that overrides get_current_user itself)
    that actually test the authenticated path.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "REQUIRE_AUTH", False)


@pytest.fixture(autouse=True)
def _disable_run_recording(monkeypatch):
    """Turn off app.observability.run_recorder's DB writes for every test.

    Most tests that exercise the planning graph (the large majority of
    tests/unit/ai and tests/integration) have nothing to do with run
    recording -- without this, each one would also attempt a real Postgres
    write per plan step, which is slow, noisy (unawaited-coroutine warnings
    once a test's own event loop closes before an in-flight write settles),
    and untested by tests that never asked for it. Mirrors `no_checkpointer`
    above: real infra off by default, opted back into explicitly by the
    handful of tests in test_run_recorder.py that actually test this.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", False)


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
