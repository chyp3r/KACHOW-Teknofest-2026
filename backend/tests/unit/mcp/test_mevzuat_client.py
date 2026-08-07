"""Unit tests for the shared low-level mevzuat-mcp resolution helpers.

Moved out of test_registry.py when pick_document_id (formerly a private
_pick_document_id in app.ai.tools.mevzuat_tools) was extracted into its own
module so app.ai.retrieval.mcp_mevzuat could reuse it without duplicating the
repealed-marker trap.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.mevzuat_client import (
    fetch_mevzuat_text,
    pick_document_id,
    resolve_and_fetch,
    resolve_mevzuat_id,
    text_of,
)

SEARCH_657 = (
    "Results: 3 total (page 1)\n"
    "- [657] DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ "
    "(Mülga Mevzuat) | mevzuatId: 335559\n"
    "- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: 102924\n"
)


def _result(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    result = MagicMock()
    result.content = [block]
    return result


# ==========================================
# text_of / pick_document_id
# ==========================================
def test_text_of_reads_the_first_content_block():
    assert text_of(_result("merhaba")) == "merhaba"


def test_text_of_tolerates_a_response_with_no_content():
    result = MagicMock()
    result.content = []
    assert text_of(result) == ""


def test_repealed_legislation_is_not_preferred():
    """657's repealed-provisions companion carries the same number and sorts
    above the law itself. Quoting it as current law would be a fabricated
    citation of exactly the kind this project exists to avoid."""
    assert pick_document_id(SEARCH_657) == "102924"


def test_repealed_result_is_still_better_than_nothing():
    only_repealed = (
        "- [657] ... YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ (Mülga Mevzuat) "
        "| mevzuatId: 335559\n"
    )
    assert pick_document_id(only_repealed) == "335559"


def test_no_results_yields_no_id():
    assert pick_document_id("Results: 0 total") is None


# ==========================================
# resolve_mevzuat_id / fetch_mevzuat_text / resolve_and_fetch
# ==========================================
@pytest.mark.asyncio
async def test_resolve_tries_the_type_filter_first():
    call = AsyncMock(return_value=_result(SEARCH_657))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        document_id = await resolve_mevzuat_id("657", "KANUN")

    assert document_id == "102924"
    call.assert_awaited_once()
    assert call.await_args.args[2]["mevzuat_tur"] == "KANUN"


@pytest.mark.asyncio
async def test_resolve_retries_unfiltered_when_the_type_filter_finds_nothing():
    call = AsyncMock(
        side_effect=[
            _result("Results: 0 total"),
            _result(
                "- [2646] RESMÎ YAZIŞMALARDA... | mevzuatId: 116932\n"
            ),
        ]
    )
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        document_id = await resolve_mevzuat_id("2646", "KANUN")

    assert document_id == "116932"
    assert call.await_count == 2
    assert "mevzuat_tur" not in call.await_args_list[1].args[2]


@pytest.mark.asyncio
async def test_resolve_with_no_type_filter_searches_unfiltered_immediately():
    call = AsyncMock(return_value=_result(SEARCH_657))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        await resolve_mevzuat_id("657", None)

    call.assert_awaited_once()
    assert "mevzuat_tur" not in call.await_args.args[2]


@pytest.mark.asyncio
async def test_fetch_text_strips_whitespace():
    call = AsyncMock(return_value=_result("  metin  \n"))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await fetch_mevzuat_text("102924") == "metin"


@pytest.mark.asyncio
async def test_resolve_and_fetch_combines_both_steps():
    call = AsyncMock(side_effect=[_result(SEARCH_657), _result("madde metni")])
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        result = await resolve_and_fetch("657", "KANUN")

    assert result == ("102924", "madde metni")


@pytest.mark.asyncio
async def test_resolve_and_fetch_returns_none_when_nothing_resolves():
    call = AsyncMock(
        side_effect=[_result("Results: 0 total"), _result("Results: 0 total")]
    )
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await resolve_and_fetch("99999", "KANUN") is None


@pytest.mark.asyncio
async def test_resolve_and_fetch_returns_none_when_the_content_is_empty():
    call = AsyncMock(side_effect=[_result(SEARCH_657), _result("   ")])
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await resolve_and_fetch("657", "KANUN") is None
