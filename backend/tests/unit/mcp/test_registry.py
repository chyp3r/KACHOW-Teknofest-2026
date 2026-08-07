"""Unit tests for MCP server registration and the live legislation tool.

Three properties matter more than the happy path:

* the server registers under its *real*, documented default configuration
  (MEVZUAT_SOURCE="mcp", MEVZUAT_MCP_ENABLED=False) -- otherwise "MCP is the
  default" is just a comment, not something a fresh checkout actually does;
* the assistant tool stays off by default regardless -- a tool the model
  cannot run must never appear in its tool list, and MEVZUAT_SOURCE wanting
  the server registered is a different question from the assistant being
  allowed to call it;
* every failure degrades to "not found" -- a third-party government site being
  slow or down must not turn a chat turn into a 500.

`build_live_legislation_tools()` reads `settings.MEVZUAT_MCP_ENABLED` live, not a
value captured at registration time, so every test that needs the tool available
keeps `patch("app.mcp.registry.settings.MEVZUAT_MCP_ENABLED", True)` open around
both `register_servers()` *and* the call to `build_live_legislation_tools()` --
building it after the patch has already exited would find the flag back at its
real (off) value and get an empty list, which is a different thing than what
these tests mean to check.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.tools.mevzuat_tools import NOT_FOUND, build_live_legislation_tools
from app.mcp.manager import mcp_manager
from app.mcp.registry import MEVZUAT_SERVER, is_registered, register_servers

SEARCH_657 = (
    "Results: 3 total (page 1)\n"
    "- [657] DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ "
    "(Mülga Mevzuat) | mevzuatId: 335559\n"
    "- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: 102924\n"
)

#: A numbered yönetmelik: KANUN-filtered search finds nothing (it is not a
#: KANUN), the unfiltered retry finds it.
SEARCH_2646_EMPTY = "Results: 0 total (page 1)\n"
SEARCH_2646_UNFILTERED = (
    "Results: 1 total (page 1)\n"
    "- [2646] RESMÎ YAZIŞMALARDA UYGULANACAK USUL VE ESASLAR HAKKINDA "
    "YÖNETMELİK (Cumhurbaşkanı Yönetmelikleri) | mevzuatId: 116932\n"
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Keep the process-wide manager from leaking between tests."""
    mcp_manager.clients.clear()
    yield
    mcp_manager.clients.clear()


def _result(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    result = MagicMock()
    result.content = [block]
    return result


def _enabled():
    """Shorthand for the patch every live-tool test needs open around its body."""
    return patch("app.mcp.registry.settings.MEVZUAT_MCP_ENABLED", True)


# ==========================================
# Registration
# ==========================================
def test_the_real_default_configuration_registers_the_server():
    """No patches: this is what a fresh checkout with no .env overrides
    actually does. MEVZUAT_SOURCE defaults to "mcp", so document analysis's
    retrieval must be able to reach the server even though the assistant's
    own MEVZUAT_MCP_ENABLED switch is still off -- proving the two switches
    are genuinely independent, not that one silently masks the other."""
    assert register_servers() == [MEVZUAT_SERVER]
    assert is_registered(MEVZUAT_SERVER) is True
    assert build_live_legislation_tools() == []


def test_enabling_the_flag_registers_the_server():
    with _enabled():
        assert register_servers() == [MEVZUAT_SERVER]
        assert is_registered(MEVZUAT_SERVER) is True


def test_registration_is_idempotent():
    """Called from startup and from test fixtures alike; must not accumulate."""
    with _enabled():
        register_servers()
        register_servers()
        assert len(mcp_manager.clients) == 1


def test_mcp_source_registers_the_server_even_with_the_assistant_flag_off():
    """MEVZUAT_SOURCE="mcp" is the document-analysis pipeline's own switch,
    independent of MEVZUAT_MCP_ENABLED (the assistant tool's switch). If
    registration only checked the assistant flag, a fresh checkout with the
    documented default (MEVZUAT_SOURCE="mcp", MEVZUAT_MCP_ENABLED=False) would
    never actually register the server -- every document analysis would
    silently fall back to the local corpus, making the new default inert."""
    with patch("app.mcp.registry.settings.MEVZUAT_MCP_ENABLED", False), \
         patch("app.mcp.registry.settings.MEVZUAT_SOURCE", "mcp"):
        assert register_servers() == [MEVZUAT_SERVER]
        assert is_registered(MEVZUAT_SERVER) is True
        # Registration is not the same question as assistant tool exposure --
        # that stays gated on MEVZUAT_MCP_ENABLED alone, unchanged by this flag.
        assert build_live_legislation_tools() == []


def test_local_source_and_disabled_flag_registers_nothing():
    """Both switches off (today's default) must still be a full no-op."""
    with patch("app.mcp.registry.settings.MEVZUAT_MCP_ENABLED", False), \
         patch("app.mcp.registry.settings.MEVZUAT_SOURCE", "local"):
        assert register_servers() == []
        assert is_registered(MEVZUAT_SERVER) is False


# ==========================================
# Tool exposure
# ==========================================
def test_no_tool_is_offered_when_the_server_is_absent():
    """The model must never be handed a tool whose call would fail."""
    assert build_live_legislation_tools() == []


def test_the_tool_appears_once_the_server_is_registered():
    with _enabled():
        register_servers()
        tools = build_live_legislation_tools()
        assert [tool.name for tool in tools] == ["search_legislation_live"]


def test_the_tool_disappears_once_the_flag_is_off_again_even_if_still_registered():
    """The flag is read live on every build, not cached from registration time --
    registration and availability are two different questions, and the second
    one must reflect the current setting even if a server was registered
    earlier under a since-changed configuration."""
    with _enabled():
        register_servers()
    assert is_registered(MEVZUAT_SERVER) is True  # registration itself persists
    assert build_live_legislation_tools() == []  # but the flag is off again now


# ==========================================
# Numbered lookups: KANUN filter, then an unfiltered retry
# ==========================================
@pytest.mark.asyncio
async def test_a_numeric_query_tries_the_type_filter_first():
    """Without the filter, 657 returns its repealed companion first."""
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        call = AsyncMock(side_effect=[_result(SEARCH_657), _result("METİN")])
        with patch.object(mcp_manager, "call_tool", call):
            await handler("657")

        assert call.await_count == 2  # one search, one content fetch -- no retry needed
        search_arguments = call.await_args_list[0].args[2]
        assert search_arguments["mevzuat_no"] == "657"
        assert search_arguments["mevzuat_tur"] == "KANUN"


@pytest.mark.asyncio
async def test_a_numbered_yonetmelik_is_found_by_retrying_without_the_type_filter():
    """Regression: the tool's own description promises 'kanun veya yönetmeliğin'
    and tells the model a numeric query is the more reliable one -- but the
    KANUN filter silently excluded every numbered yönetmelik, tüzük and KHK,
    steering the model into the one query shape guaranteed to fail for them.
    2646 (the correspondence regulation itself) is a CB_YONETMELIK, not a
    KANUN, so the first (filtered) search finds nothing and this must fall
    through to a second, unfiltered attempt rather than giving up."""
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        call = AsyncMock(
            side_effect=[
                _result(SEARCH_2646_EMPTY),  # 1st: KANUN-filtered, no hits
                _result(SEARCH_2646_UNFILTERED),  # 2nd: unfiltered, found
                _result("Resmî Yazışmalarda..."),  # 3rd: content fetch
            ]
        )
        with patch.object(mcp_manager, "call_tool", call):
            answer = await handler("2646")

        assert answer != NOT_FOUND
        assert "mevzuat_id=116932" in answer
        assert call.await_count == 3

        first_search, second_search = call.await_args_list[0], call.await_args_list[1]
        assert first_search.args[2] == {
            "mevzuat_no": "2646", "mevzuat_tur": "KANUN", "page_size": 5
        }
        assert second_search.args[2] == {"mevzuat_no": "2646", "page_size": 5}


@pytest.mark.asyncio
async def test_a_number_matching_nothing_at_all_reads_as_not_found():
    """Both attempts exhausted, no fabricated fallback."""
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        call = AsyncMock(
            side_effect=[_result(SEARCH_2646_EMPTY), _result("Results: 0 total")]
        )
        with patch.object(mcp_manager, "call_tool", call):
            assert await handler("99999") == NOT_FOUND
        assert call.await_count == 2  # never reaches a content fetch


# ==========================================
# Degradation
# ==========================================
@pytest.mark.asyncio
async def test_an_unreachable_server_reads_as_not_found():
    """A government site being down is a missing result, not a broken chat."""
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        with patch.object(
            mcp_manager, "call_tool", AsyncMock(side_effect=ConnectionError("refused"))
        ):
            assert await handler("657") == NOT_FOUND


@pytest.mark.asyncio
async def test_a_slow_server_is_cut_off_rather_than_stalling_the_turn():
    import asyncio

    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        async def _hang(*_args, **_kwargs):
            await asyncio.sleep(30)

        with patch("app.ai.tools.mevzuat_tools.settings.MEVZUAT_MCP_TIMEOUT_SECONDS", 0.05):
            with patch.object(mcp_manager, "call_tool", _hang):
                assert await handler("657") == NOT_FOUND


@pytest.mark.asyncio
async def test_an_empty_document_reads_as_not_found():
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        call = AsyncMock(side_effect=[_result(SEARCH_657), _result("   ")])
        with patch.object(mcp_manager, "call_tool", call):
            assert await handler("657") == NOT_FOUND


@pytest.mark.asyncio
async def test_a_long_law_is_truncated_before_reaching_the_model():
    """657 runs to roughly half a million characters; unbounded it would blow
    the context window."""
    with _enabled():
        register_servers()
        handler = build_live_legislation_tools()[0].handler

        call = AsyncMock(side_effect=[_result(SEARCH_657), _result("x" * 500_000)])
        with patch.object(mcp_manager, "call_tool", call):
            answer = await handler("657")

        assert len(answer) < 10_000
        assert "kısaltıldı" in answer
