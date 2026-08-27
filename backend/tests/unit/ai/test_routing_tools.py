"""Unit tests for `app.ai.tools.routing_tools.build_routing_tools` -- the
`suggest_unit` tool the assist step's model may call to answer a unit-routing
question directly in chat."""

from unittest.mock import AsyncMock

import pytest

from app.ai.tools.routing_tools import build_routing_tools

ROUTING_STATE = {
    "routed_unit": "İnsan Kaynakları Daire Başkanlığı",
    "reasoning": "Yazı personel özlük işlerini konu almaktadır.",
    "alternative_units": ["Hukuk Müşavirliği"],
    "requires_human_approval": False,
}


def _tool(**overrides):
    graph = AsyncMock(ainvoke=AsyncMock(return_value={**ROUTING_STATE, **overrides.pop("state", {})}))
    kwargs = {"company_id": "acme", "routing_graph": graph, **overrides}
    return build_routing_tools(**kwargs)[0], graph


@pytest.mark.asyncio
async def test_it_routes_the_active_draft_text_when_present():
    tool, graph = _tool(active_draft_text="Sayın Makam, personel izin talebidir.")

    result = await tool.handler(konu="")

    graph.ainvoke.assert_awaited_once()
    sent = graph.ainvoke.await_args.args[0]
    assert sent["draft"] == "Sayın Makam, personel izin talebidir."
    assert sent["company_id"] == "acme"
    # confidence_score deliberately not sent -- routing_node defaults it to 100.
    assert "confidence_score" not in sent
    assert "Önerilen birim: İnsan Kaynakları Daire Başkanlığı" in result
    assert "Gerekçe:" in result
    assert "Alternatif birimler: Hukuk Müşavirliği" in result


@pytest.mark.asyncio
async def test_the_document_text_is_used_when_there_is_no_active_draft():
    tool, graph = _tool(document_text="Evrak metni burada.")

    await tool.handler(konu="")

    assert graph.ainvoke.await_args.args[0]["draft"] == "Evrak metni burada."


@pytest.mark.asyncio
async def test_the_konu_argument_is_the_fallback_when_nothing_is_attached():
    tool, graph = _tool()

    await tool.handler(konu="Bir vatandaşın bilgi edinme başvurusu.")

    assert graph.ainvoke.await_args.args[0]["draft"] == "Bir vatandaşın bilgi edinme başvurusu."


@pytest.mark.asyncio
async def test_it_asks_for_a_topic_when_it_has_no_text_at_all():
    tool, graph = _tool()

    result = await tool.handler(konu="")

    graph.ainvoke.assert_not_awaited()
    assert "konu" in result.lower()


@pytest.mark.asyncio
async def test_a_low_confidence_routing_result_carries_a_review_note():
    tool, _ = _tool(
        active_draft_text="x",
        state={"requires_human_approval": True, "alternative_units": []},
    )

    result = await tool.handler(konu="")

    assert "teyidi önerilir" in result


@pytest.mark.asyncio
async def test_a_routing_failure_degrades_to_a_message_not_an_exception():
    graph = AsyncMock(ainvoke=AsyncMock(side_effect=RuntimeError("boom")))
    tool = build_routing_tools(company_id="acme", routing_graph=graph, active_draft_text="x")[0]

    result = await tool.handler(konu="")

    assert "hata" in result.lower()


@pytest.mark.asyncio
async def test_the_raw_state_reaches_the_side_channel_callback():
    recorded = []
    tool, _ = _tool(active_draft_text="x", on_routing_result=recorded.append)

    await tool.handler(konu="")

    assert recorded and recorded[0]["routed_unit"] == "İnsan Kaynakları Daire Başkanlığı"


def test_the_tool_is_always_offered():
    tools = build_routing_tools(company_id="acme", routing_graph=AsyncMock())
    assert [t.name for t in tools] == ["suggest_unit"]
