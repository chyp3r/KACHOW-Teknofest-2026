"""Unit tests for the shared low-level mevzuat-mcp resolution helpers.

Moved out of test_registry.py when pick_document_id (formerly a private
_pick_document_id in app.ai.tools.mevzuat_tools) was extracted into its own
module so app.ai.retrieval.mcp_mevzuat could reuse it without duplicating the
repealed-marker trap.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.mevzuat_client import (
    excerpt_within,
    fetch_mevzuat_text,
    pick_document_id,
    resolve_and_fetch,
    resolve_mevzuat_id,
    search_and_excerpt,
    search_by_phrase,
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


# ==========================================
# search_by_phrase / excerpt_within / search_and_excerpt
# ==========================================
SEARCH_BY_TOPIC = "- [4982] BİLGİ EDİNME HAKKI KANUNU (Kanunlar) | mevzuatId: 55555\n"


@pytest.mark.asyncio
async def test_search_by_phrase_uses_phrase_and_disables_title_only_search():
    """The server defaults `basliktaAra` to True (title-only search) --
    a topic query almost never matches that way, so this must pass it
    explicitly as False to actually search the content."""
    call = AsyncMock(return_value=_result(SEARCH_BY_TOPIC))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        document_id = await search_by_phrase("bilgi edinme başvurusu")

    assert document_id == "55555"
    call.assert_awaited_once()
    args = call.await_args.args[2]
    assert args["phrase"] == "bilgi edinme başvurusu"
    assert args["basliktaAra"] is False


@pytest.mark.asyncio
async def test_search_by_phrase_skips_repealed_records_like_the_numeric_path():
    """Shares pick_document_id with the numeric path -- same repealed-marker
    trap applies to a phrase-matched result."""
    call = AsyncMock(return_value=_result(SEARCH_657))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await search_by_phrase("devlet memuru izin hakkı") == "102924"


@pytest.mark.asyncio
async def test_search_by_phrase_returns_none_when_nothing_matches():
    call = AsyncMock(return_value=_result("Results: 0 total"))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await search_by_phrase("tamamen alakasız bir konu") is None


@pytest.mark.asyncio
async def test_excerpt_within_calls_search_within_mevzuat_with_the_keyword():
    call = AsyncMock(return_value=_result("[Madde 7] ... eşleşen pasaj ..."))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        excerpt = await excerpt_within("55555", "başvuru süresi", max_results=3)

    assert excerpt == "[Madde 7] ... eşleşen pasaj ..."
    call.assert_awaited_once_with(
        "mevzuat",
        "search_within_mevzuat",
        {"mevzuat_id": "55555", "keyword": "başvuru süresi", "max_results": 3},
    )


@pytest.mark.asyncio
async def test_excerpt_within_returns_empty_string_when_nothing_matches():
    call = AsyncMock(return_value=_result(""))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await excerpt_within("55555", "hiç geçmeyen terim") == ""


@pytest.mark.asyncio
async def test_search_and_excerpt_chains_phrase_search_then_targeted_excerpt():
    call = AsyncMock(
        side_effect=[_result(SEARCH_BY_TOPIC), _result("[Madde 4] ilgili pasaj")]
    )
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        result = await search_and_excerpt("bilgi edinme başvurusu")

    assert result == ("55555", "[Madde 4] ilgili pasaj")
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_search_and_excerpt_returns_none_when_no_law_matches():
    call = AsyncMock(return_value=_result("Results: 0 total"))
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await search_and_excerpt("tamamen alakasız bir konu") is None
    call.assert_awaited_once()  # excerpt_within never reached


@pytest.mark.asyncio
async def test_search_and_excerpt_returns_none_when_the_law_matches_but_no_passage_does():
    """A matched law with no excerpt is not the same as a full-text
    fallback -- this function's entire purpose is a *targeted* excerpt, so
    falling back to the (potentially half-million character) full text
    would defeat it."""
    call = AsyncMock(side_effect=[_result(SEARCH_BY_TOPIC), _result("   ")])
    with patch("app.mcp.mevzuat_client.mcp_manager.call_tool", call):
        assert await search_and_excerpt("bilgi edinme başvurusu") is None
