"""Proof that NODE_DURATION is actually populated per plan step.

`NODE_DURATION` used to be a declared Prometheus collector nobody
incremented -- see the scope note that used to sit at the top of
`app/observability/ai_metrics.py`. Mirrors test_hitl_flow.py's /
test_memory_consolidation.py's pattern: only the sub-graphs an assist-intent
turn never touches are mocked away, so `_execute_one_step`'s real timing
code runs.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph
from app.observability.ai_metrics import NODE_DURATION


def _total_seconds(node: str, status: str) -> float:
    # Histogram buckets are non-cumulative internally (each observation lands
    # in exactly one bucket; Prometheus computes the cumulative view at scrape
    # time) and there is no public per-label observation counter, so the sum
    # of observed durations is the stable signal that at least one
    # observation happened -- a real async graph step always takes a
    # measurable, non-zero amount of wall-clock time.
    return NODE_DURATION.labels(graph="planning", node=node, status=status)._sum.get()


@pytest.mark.asyncio
async def test_node_duration_is_recorded_for_a_completed_assist_step(fake_llm, fake_fast_llm):
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
    config = {"configurable": {"thread_id": "node-duration-test"}}

    before = _total_seconds("assist", "completed")
    await graph.ainvoke({"input_text": "Merhaba", "document_id": None}, config=config)
    after = _total_seconds("assist", "completed")

    assert after > before
