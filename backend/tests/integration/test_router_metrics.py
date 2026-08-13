"""Proof that the router's own metrics are actually populated per turn.

`ROUTER_DECISIONS`/`ROUTER_CONFIDENCE` used to not exist at all -- the only
visibility into how often the router asks a clarifying question, or which
mechanism decided, was a `run_recorder` DB row. Mirrors
`test_node_duration_metric.py`'s pattern: only the sub-graphs an
assist-intent turn never touches are mocked away, so `planning_node`'s real
metric-recording code runs.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph
from app.observability.ai_metrics import ROUTER_CONFIDENCE, ROUTER_DECISIONS


def _decisions_total(intent: str, source: str) -> float:
    return ROUTER_DECISIONS.labels(intent=intent, source=source)._value.get()


def _confidence_observations(source: str) -> float:
    return ROUTER_CONFIDENCE.labels(source=source)._sum.get()


@pytest.mark.asyncio
async def test_a_completed_turn_increments_router_decisions_and_confidence(
    fake_llm, fake_fast_llm
):
    fake_llm.stream_chunks = ["merhaba"]
    graph = create_planning_graph(
        llm_client=fake_llm,
        document_analysis_graph=AsyncMock(),
        rag_graph=AsyncMock(),
        draft_graph=AsyncMock(),
        routing_graph=AsyncMock(),
        fast_llm_client=fake_fast_llm,
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "router-metrics-test"}}

    # "Merhaba" resolves lexically and decisively (see intent_rules.py's
    # `assist.greeting`), so this turn's source is deterministic: "fused".
    before_decisions = _decisions_total("assist", "fused")
    before_confidence = _confidence_observations("fused")

    await graph.ainvoke({"input_text": "Merhaba", "document_id": None}, config=config)

    assert _decisions_total("assist", "fused") == before_decisions + 1
    assert _confidence_observations("fused") > before_confidence
