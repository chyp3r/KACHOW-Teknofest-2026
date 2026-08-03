"""Unit tests for the unit-routing sub-graph's deterministic short-circuits.

RoutingState is declared with total=False and must explicitly list every key
the node writes -- LangGraph silently drops updates for keys absent from the
state schema, which is why routed_unit/reasoning/priority previously never
reached the API response even though the node returned them. These tests
guard the full key set landing on every path, not just the happy one.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.router import RouterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.routing_graph import (
    HUMAN_APPROVAL_SCORE_THRESHOLD,
    HUMAN_APPROVAL_UNIT,
    RouteOutput,
    create_routing_graph,
)

EXPECTED_KEYS = {"final_destination", "justification", "routed_unit", "reasoning", "priority"}


@pytest.mark.asyncio
async def test_an_empty_draft_short_circuits_to_human_approval_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient))

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke({"draft": "   ", "confidence_score": 100.0})

    mock_run.assert_not_called()
    assert result["routed_unit"] == HUMAN_APPROVAL_UNIT
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_low_confidence_score_forces_human_approval_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient))

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke(
            {"draft": "Bir taslak metni.", "confidence_score": HUMAN_APPROVAL_SCORE_THRESHOLD - 1}
        )

    mock_run.assert_not_called()
    assert result["routed_unit"] == HUMAN_APPROVAL_UNIT
    assert result["priority"] == "Yüksek"


@pytest.mark.asyncio
async def test_a_confident_draft_is_routed_per_the_model_decision():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient))

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Mali İşler", justification="Bütçe talebiyle ilgili.")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"draft": "Bütçe artışı talep ediyorum.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
    assert result["reasoning"] == "Bütçe talebiyle ilgili."
    assert result["priority"] == "Normal"
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_model_failure_degrades_to_human_approval_rather_than_raising():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient))

    async def fake_run_structured(**kwargs):
        raise RuntimeError("provider unavailable")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"draft": "Bir taslak metni.", "confidence_score": 90.0})

    assert result["routed_unit"] == HUMAN_APPROVAL_UNIT


@pytest.mark.asyncio
async def test_missing_confidence_score_defaults_to_full_confidence():
    """A caller that omits confidence_score (e.g. the standalone
    /routing/suggest endpoint's default) must not be treated as low-confidence."""
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient))

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Destek Hizmetleri", justification="r")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"draft": "Bir taslak metni."})

    assert result["routed_unit"] == "Destek Hizmetleri"
