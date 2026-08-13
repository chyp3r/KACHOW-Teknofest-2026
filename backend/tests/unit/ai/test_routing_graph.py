"""Unit tests for the unit-routing sub-graph's deterministic short-circuits.

RoutingState is declared with total=False and must explicitly list every key
the node writes -- LangGraph silently drops updates for keys absent from the
state schema, which is why routed_unit/reasoning/priority previously never
reached the API response even though the node returned them. These tests
guard the full key set landing on every path, not just the happy one.

Units are no longer a fixed policy list -- every test supplies its own
``units_provider`` (a fake standing in for
``app.domains.units.provider.get_active_units_for_routing``), the same way
production wires a real one through ``app.api.dependency.get_routing_graph``.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.ai.agents.router import RouterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.routing_graph import (
    HUMAN_APPROVAL_SCORE_THRESHOLD,
    RouteOutput,
    create_routing_graph,
)

EXPECTED_KEYS = {
    "final_destination",
    "justification",
    "routed_unit",
    "reasoning",
    "priority",
    "requires_human_approval",
}

SOME_UNITS = [("Mali İşler", "Bütçe ve ödemeler."), ("Destek Hizmetleri", "Genel destek.")]


async def _units_provider(company_id: str, units=SOME_UNITS):
    return units


@pytest.mark.asyncio
async def test_an_empty_draft_short_circuits_to_human_approval_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke({"company_id": "company-1", "draft": "   ", "confidence_score": 100.0})

    mock_run.assert_not_called()
    assert result["routed_unit"] is None
    assert result["requires_human_approval"] is True
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_low_confidence_score_forces_human_approval_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke(
            {
                "company_id": "company-1",
                "draft": "Bir taslak metni.",
                "confidence_score": HUMAN_APPROVAL_SCORE_THRESHOLD - 1,
            }
        )

    mock_run.assert_not_called()
    assert result["routed_unit"] is None
    assert result["priority"] == "Yüksek"
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_no_active_units_short_circuits_to_human_approval_without_calling_the_model():
    """An admin having deleted/disabled every unit must degrade gracefully,
    not crash or hallucinate a destination."""
    graph = create_routing_graph(
        llm_client=MagicMock(spec=BaseLLMClient), units_provider=lambda company_id: _units_provider(company_id, [])
    )

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bir taslak metni.", "confidence_score": 90.0})

    mock_run.assert_not_called()
    assert result["routed_unit"] is None
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_a_confident_draft_is_routed_per_the_model_decision():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Mali İşler", justification="Bütçe talebiyle ilgili.")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bütçe artışı talep ediyorum.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
    assert result["reasoning"] == "Bütçe talebiyle ilgili."
    assert result["priority"] == "Normal"
    assert result["requires_human_approval"] is False
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_unit_outside_the_offered_list_degrades_to_human_approval():
    """A hallucinated/stale unit name must not be trusted -- it's validated
    against the units actually offered in this call's prompt."""
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="İnsan Onayı Gerekli", justification="Belirsiz.")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Belirsiz bir talep.", "confidence_score": 90.0})

    assert result["routed_unit"] is None
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_a_model_failure_degrades_to_human_approval_rather_than_raising():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        raise RuntimeError("provider unavailable")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bir taslak metni.", "confidence_score": 90.0})

    assert result["routed_unit"] is None
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_missing_confidence_score_defaults_to_full_confidence():
    """A caller that omits confidence_score (e.g. the standalone
    /routing/suggest endpoint's default) must not be treated as low-confidence."""
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Destek Hizmetleri", justification="r")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bir taslak metni."})

    assert result["routed_unit"] == "Destek Hizmetleri"
    assert result["requires_human_approval"] is False
