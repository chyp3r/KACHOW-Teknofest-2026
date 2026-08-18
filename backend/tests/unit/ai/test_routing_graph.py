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

Routing never leaves ``routed_unit`` unset just because the model couldn't
decide, failed, or was never confident enough to be asked -- see
``routing_graph._best_effort_unit``. The only branch that still leaves it
``None`` is a company with zero active units, which has nothing to suggest
by construction.
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
    "alternative_units",
}

SOME_UNITS = [("Mali İşler", "Bütçe ve ödemeler."), ("Destek Hizmetleri", "Genel destek.")]


async def _units_provider(company_id: str, units=SOME_UNITS):
    return units


@pytest.mark.asyncio
async def test_an_empty_draft_still_gets_a_best_effort_unit_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke({"company_id": "company-1", "draft": "   ", "confidence_score": 100.0})

    mock_run.assert_not_called()
    assert result["routed_unit"] in {name for name, _ in SOME_UNITS}
    assert result["requires_human_approval"] is True
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_low_confidence_score_still_gets_a_best_effort_unit_without_calling_the_model():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke(
            {
                "company_id": "company-1",
                "draft": "Bütçe artışı talep ediyorum.",
                "confidence_score": HUMAN_APPROVAL_SCORE_THRESHOLD - 1,
            }
        )

    mock_run.assert_not_called()
    # The draft's own vocabulary ("bütçe") overlaps "Mali İşler"'s
    # description -- proof this is a real content-based pick, not an
    # arbitrary first-unit default.
    assert result["routed_unit"] == "Mali İşler"
    assert result["priority"] == "Yüksek"
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_no_active_units_is_the_one_case_that_still_leaves_the_destination_unset():
    """An admin having deleted/disabled every unit must degrade gracefully,
    not crash or hallucinate a destination -- and is the only branch with
    genuinely nothing to suggest."""
    graph = create_routing_graph(
        llm_client=MagicMock(spec=BaseLLMClient), units_provider=lambda company_id: _units_provider(company_id, [])
    )

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bir taslak metni.", "confidence_score": 90.0})

    mock_run.assert_not_called()
    assert result["routed_unit"] is None
    assert result["alternative_units"] == []
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_a_confident_draft_is_routed_per_the_model_decision():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(
            destination="Mali İşler", alternative="Destek Hizmetleri", justification="Bütçe talebiyle ilgili."
        )

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bütçe artışı talep ediyorum.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
    assert result["alternative_units"] == ["Destek Hizmetleri"]
    assert result["reasoning"] == "Bütçe talebiyle ilgili."
    assert result["priority"] == "Normal"
    assert result["requires_human_approval"] is False
    assert set(result) >= EXPECTED_KEYS


@pytest.mark.asyncio
async def test_a_missing_or_invalid_model_alternative_is_backfilled_deterministically():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Mali İşler", alternative="", justification="r")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bir taslak metni.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
    assert result["alternative_units"] == ["Destek Hizmetleri"]


@pytest.mark.asyncio
async def test_a_unit_outside_the_offered_list_falls_back_to_a_best_effort_pick():
    """A hallucinated/stale unit name must not be trusted -- it's validated
    against the units actually offered in this call's prompt, and a
    best-effort pick is substituted rather than leaving the field blank."""
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        return RouteOutput(destination="Var Olmayan Birim", justification="Belirsiz.")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bütçe artışı talep ediyorum.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_a_model_failure_falls_back_to_a_best_effort_pick_rather_than_raising():
    graph = create_routing_graph(llm_client=MagicMock(spec=BaseLLMClient), units_provider=_units_provider)

    async def fake_run_structured(**kwargs):
        raise RuntimeError("provider unavailable")

    with patch.object(RouterAgent, "run_structured", side_effect=fake_run_structured):
        result = await graph.ainvoke({"company_id": "company-1", "draft": "Bütçe artışı talep ediyorum.", "confidence_score": 90.0})

    assert result["routed_unit"] == "Mali İşler"
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


@pytest.mark.asyncio
async def test_a_single_unit_company_has_no_alternative_to_offer():
    graph = create_routing_graph(
        llm_client=MagicMock(spec=BaseLLMClient),
        units_provider=lambda company_id: _units_provider(company_id, SOME_UNITS[:1]),
    )

    with patch.object(RouterAgent, "run_structured") as mock_run:
        result = await graph.ainvoke(
            {"company_id": "company-1", "draft": "Bir taslak metni.", "confidence_score": 10.0}
        )

    mock_run.assert_not_called()
    assert result["routed_unit"] == "Mali İşler"
    assert result["alternative_units"] == []
