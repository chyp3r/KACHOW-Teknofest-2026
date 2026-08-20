"""Unit tests for `app.ai.tools.handoff_tools.build_handoff_tools` -- the
`request_handoff` tool the assist step's model may call (Faz 7)."""

import pytest

from app.ai.tools.handoff_tools import build_handoff_tools


def _find(tools, name):
    return next(tool for tool in tools if tool.name == name)


@pytest.mark.asyncio
async def test_a_draft_handoff_request_is_recorded():
    recorded = []
    tools = build_handoff_tools(has_active_draft=False, on_handoff_requested=recorded.append)

    result = await _find(tools, "request_handoff").handler(target="draft", reason="test")

    assert recorded == [{"target": "draft", "reason": "test"}]
    assert "yönlendiriliyor" in result.lower()


@pytest.mark.asyncio
async def test_a_revise_handoff_request_is_recorded_when_a_draft_is_active():
    recorded = []
    tools = build_handoff_tools(has_active_draft=True, on_handoff_requested=recorded.append)

    await _find(tools, "request_handoff").handler(target="revise", reason="unvanı düzelt")

    assert recorded == [{"target": "revise", "reason": "unvanı düzelt"}]


@pytest.mark.asyncio
async def test_a_revise_handoff_request_is_refused_without_an_active_draft():
    """Revise is never handed off to without an active draft -- mirrors the
    same guarantee intent_scorer.score_intents already gives the
    deterministic routing path (revise's own rules are gated on
    has_active_draft)."""
    recorded = []
    tools = build_handoff_tools(has_active_draft=False, on_handoff_requested=recorded.append)

    result = await _find(tools, "request_handoff").handler(target="revise", reason="unvanı düzelt")

    assert recorded == []
    assert "aktif bir taslak yok" in result.lower()


def test_the_tool_is_always_offered_regardless_of_state():
    """Unlike propose_transfer (gated on a configured provider/identity),
    request_handoff needs no external dependency -- it should always be
    offered."""
    tools = build_handoff_tools(has_active_draft=False, on_handoff_requested=lambda _: None)
    assert len(tools) == 1
    assert tools[0].name == "request_handoff"
