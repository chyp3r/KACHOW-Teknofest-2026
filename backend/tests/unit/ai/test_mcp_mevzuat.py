"""Unit tests for MCP-first legislation retrieval.

Two properties matter more than the happy path:

* `McpMevzuatRetriever.retrieve()` never performs network I/O -- it only
  reads whatever `warm_up()` last built, and returns empty immediately when
  nothing is warm yet. This is what keeps a live fetch off the per-request
  path (see the class's own docstring for the timing reasoning).
* `FallbackMevzuatRetriever` falls through to the local retriever on *both*
  an exception and a successful-but-empty primary result, not just the
  former.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.ai.retrieval.mcp_mevzuat import (
    CURATED_LEGISLATION,
    FallbackMevzuatRetriever,
    McpMevzuatRetriever,
)


def _search_result(mevzuat_id: str) -> MagicMock:
    block = MagicMock()
    block.text = f"- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: {mevzuat_id}\n"
    result = MagicMock()
    result.content = [block]
    return result


def _content_result(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    result = MagicMock()
    result.content = [block]
    return result


# ==========================================
# McpMevzuatRetriever
# ==========================================
@pytest.mark.asyncio
async def test_retrieve_before_warm_up_returns_empty_with_no_network_call():
    retriever = McpMevzuatRetriever()
    call = AsyncMock()
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await retriever.retrieve("izin talebi") == []
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_warm_up_does_nothing_when_the_server_is_not_registered():
    retriever = McpMevzuatRetriever()
    call = AsyncMock()
    with patch("app.ai.retrieval.mcp_mevzuat.is_registered", return_value=False), \
         patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        await retriever.warm_up()

    assert retriever.is_warm is False
    call.assert_not_awaited()


def _fake_mevzuat_id(number: str) -> str:
    """A synthetic-but-purely-numeric id: pick_document_id's regex requires
    digits right after "mevzuatId:" (matching the server's real id format),
    so a non-numeric placeholder like "id-2646" would silently fail to
    parse and every law would look like a resolution failure."""
    return f"9{number}"


def _call_tool_by_number(*, failing_numbers: frozenset[str] = frozenset()):
    """A call_tool fake that judges each call by its own arguments (which law
    number it's resolving, or which id it's fetching) rather than by a fixed
    position in a flat list. All seven laws fetch concurrently via
    asyncio.gather, so a position-indexed side_effect list would silently
    assume a specific cross-task call interleaving that asyncio does not
    guarantee.
    """
    no_hit = MagicMock()
    no_hit.content = []

    async def _call_tool(_server, tool, arguments):
        if tool == "search_mevzuat":
            number = arguments["mevzuat_no"]
            if number in failing_numbers:
                return no_hit
            return _search_result(_fake_mevzuat_id(number))
        assert tool == "get_mevzuat_content"
        mevzuat_id = arguments["mevzuat_id"]
        return _content_result(f"MADDE 1- {mevzuat_id} metni.")

    return _call_tool


@pytest.mark.asyncio
async def test_warm_up_indexes_every_curated_law_and_retrieve_ranks_it():
    with patch("app.ai.retrieval.mcp_mevzuat.is_registered", return_value=True), \
         patch("app.mcp.mevzuat_client.mcp_manager.call_tool", side_effect=_call_tool_by_number()):
        retriever = McpMevzuatRetriever()
        await retriever.warm_up()

    assert retriever.is_warm is True
    results = await retriever.retrieve("metni", limit=3)
    assert len(results) > 0
    assert all(isinstance(doc, Document) for doc in results)
    # Any successfully-fetched law's chunks carry the shared mcp: source tag.
    assert all(doc.metadata["source"].startswith("mcp:") for doc in results)


@pytest.mark.asyncio
async def test_warm_up_tolerates_some_laws_failing():
    """One law's resolution failing (e.g. a repealed-only result) must not
    cost the other six their place in the index."""
    failing_number = CURATED_LEGISLATION[0].number
    with patch("app.ai.retrieval.mcp_mevzuat.is_registered", return_value=True), \
         patch(
             "app.mcp.mevzuat_client.mcp_manager.call_tool",
             side_effect=_call_tool_by_number(failing_numbers=frozenset({failing_number})),
         ):
        retriever = McpMevzuatRetriever()
        await retriever.warm_up()

    assert retriever.is_warm is True
    results = await retriever.retrieve("metni", limit=10)
    sources = {doc.metadata["source"] for doc in results}
    assert f"mcp:{_fake_mevzuat_id(failing_number)}" not in sources
    # The other six laws still made it in.
    assert len(sources) == len(CURATED_LEGISLATION) - 1


@pytest.mark.asyncio
async def test_warm_up_stays_cold_when_every_law_fails():
    no_hit = MagicMock()
    no_hit.content = []
    # Two attempts (filtered + unfiltered) per law, all empty.
    call = AsyncMock(return_value=no_hit)

    with patch("app.ai.retrieval.mcp_mevzuat.is_registered", return_value=True), \
         patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        retriever = McpMevzuatRetriever()
        await retriever.warm_up()

    assert retriever.is_warm is False
    assert await retriever.retrieve("her hangi bir sorgu") == []


@pytest.mark.asyncio
async def test_a_hung_fetch_is_cut_off_rather_than_hanging_warm_up_forever():
    """Bounds each law's fetch independently (see _fetch_one's docstring) --
    without it, one unresponsive call could hold up asyncio.gather for as
    long as the caller lets warm_up() run, instead of the usual per-lookup
    cap. All seven calls hang uniformly here (no ordering assumptions needed
    about which of seven concurrent fetches the mock sees first); what this
    proves is that warm_up() returns promptly instead of hanging for the
    full 30s the mock would otherwise sleep."""
    import asyncio

    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(30)

    with patch("app.ai.retrieval.mcp_mevzuat.is_registered", return_value=True), \
         patch("app.mcp.mevzuat_client.mcp_manager.call_tool", side_effect=_hang), \
         patch("app.ai.retrieval.mcp_mevzuat.settings.MEVZUAT_MCP_TIMEOUT_SECONDS", 0.05):
        retriever = McpMevzuatRetriever()
        await asyncio.wait_for(retriever.warm_up(), timeout=5.0)

    # Every law timed out, so no index could be built -- retrieve() falls
    # through to the caller's local fallback rather than fabricating one.
    assert retriever.is_warm is False


# ==========================================
# FallbackMevzuatRetriever
# ==========================================
@pytest.mark.asyncio
async def test_a_nonempty_primary_result_is_used_directly():
    primary = AsyncMock()
    primary.retrieve.return_value = [Document(page_content="x", metadata={})]
    fallback = AsyncMock()

    retriever = FallbackMevzuatRetriever(primary, fallback)
    result = await retriever.retrieve("q", 3)

    assert len(result) == 1
    fallback.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_empty_primary_result_falls_through_to_local():
    primary = AsyncMock()
    primary.retrieve.return_value = []
    fallback = AsyncMock()
    fallback.retrieve.return_value = [Document(page_content="local", metadata={})]

    retriever = FallbackMevzuatRetriever(primary, fallback)
    result = await retriever.retrieve("q", 3)

    assert [doc.page_content for doc in result] == ["local"]
    fallback.retrieve.assert_awaited_once_with("q", 3)


@pytest.mark.asyncio
async def test_a_primary_exception_falls_through_to_local():
    primary = AsyncMock()
    primary.retrieve.side_effect = ConnectionError("mcp unreachable")
    fallback = AsyncMock()
    fallback.retrieve.return_value = [Document(page_content="local", metadata={})]

    retriever = FallbackMevzuatRetriever(primary, fallback)
    result = await retriever.retrieve("q", 3)

    assert [doc.page_content for doc in result] == ["local"]


@pytest.mark.asyncio
async def test_warm_up_passes_through_to_a_primary_that_has_one():
    primary = AsyncMock()
    fallback = AsyncMock()

    retriever = FallbackMevzuatRetriever(primary, fallback)
    await retriever.warm_up()

    primary.warm_up.assert_awaited_once()


@pytest.mark.asyncio
async def test_warm_up_is_a_no_op_for_a_primary_without_one():
    """The local-only HybridRetriever has no warm_up -- must not crash."""
    primary = MagicMock(spec=[])  # no attributes at all, in particular no warm_up
    fallback = AsyncMock()

    retriever = FallbackMevzuatRetriever(primary, fallback)
    await retriever.warm_up()  # must not raise


@pytest.mark.asyncio
async def test_warm_up_failure_is_swallowed_not_propagated():
    primary = AsyncMock()
    primary.warm_up.side_effect = RuntimeError("mcp server unreachable")
    fallback = AsyncMock()

    retriever = FallbackMevzuatRetriever(primary, fallback)
    await retriever.warm_up()  # must not raise
