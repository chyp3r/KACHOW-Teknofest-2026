"""End-to-end test for the draft_revision plan through the planning graph.

Exercises the actual compiled planning graph -- planning_node's intent
resolution, execute_step_node's readiness scheduling, _run_draft_revision's
input assembly -- with only the LLM-backed sub-graphs mocked, same pattern as
test_hitl_flow.py. Proves the three properties the "son taslağı düzenle"
feature depends on: the plan a message with has_last_draft=True resolves to
skips classification and routing, the sub-graph call it does make actually
carries the previous draft's content and the new instruction, and a message
with no draft to revise is completely unaffected.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.planning_graph import create_planning_graph

LAST_DRAFT = {
    "id": "draft-1",
    "content": "Sayın Makam,\n\nArz ederim.\n\nAli Veli",
    "document_id": "uploads/original.pdf",
    "correspondence_type": "response_letter",
    "routed_unit": None,
    "status": "COMPLETED",
    "confidence_score": 90.0,
}

REVISED_DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": "Sayın Makam,\n\nArz ederiz.\n\nAli Veli, Zeynep Kaya",
    "confidence_score": 92.0,
    "combined_score": 92.0,
    "requires_human_approval": False,
}


def _build_graph():
    document_analysis_graph = AsyncMock()
    rag_graph = AsyncMock()
    draft_graph = AsyncMock(ainvoke=AsyncMock(return_value=dict(REVISED_DRAFT_RESULT)))
    routing_graph = AsyncMock()
    graph = create_planning_graph(
        llm_client=MagicMock(spec=BaseLLMClient),
        document_analysis_graph=document_analysis_graph,
        rag_graph=rag_graph,
        draft_graph=draft_graph,
        routing_graph=routing_graph,
        checkpointer=MemorySaver(),
    )
    return graph, document_analysis_graph, draft_graph, routing_graph


@pytest.mark.asyncio
async def test_a_revision_request_skips_classification_and_routing():
    graph, document_analysis_graph, draft_graph, routing_graph = _build_graph()
    config = {"configurable": {"thread_id": "revision-flow-0"}}

    result = await graph.ainvoke(
        {
            "input_text": "Son taslaktaki 'ben' ifadelerini 'biz' yap",
            "document_id": None,
            "last_draft": LAST_DRAFT,
        },
        config=config,
    )

    document_analysis_graph.ainvoke.assert_not_called()
    routing_graph.ainvoke.assert_not_called()
    draft_graph.ainvoke.assert_called_once()
    assert result["plan_intent"] == "draft_revision"
    assert result["plan_steps"] == ["draft"]
    assert result["final_output"]["draft"]["draft"] == REVISED_DRAFT_RESULT["draft"]


@pytest.mark.asyncio
async def test_the_draft_subgraph_receives_the_previous_content_and_new_instruction():
    graph, _document_analysis_graph, draft_graph, _routing_graph = _build_graph()
    config = {"configurable": {"thread_id": "revision-flow-1"}}
    instruction = "Son taslaktaki 'ben' ifadelerini 'biz' yap"

    await graph.ainvoke(
        {"input_text": instruction, "document_id": None, "last_draft": LAST_DRAFT},
        config=config,
    )

    draft_input = draft_graph.ainvoke.call_args.args[0]
    assert draft_input["previous_draft"] == LAST_DRAFT["content"]
    assert draft_input["revision_instruction"] == instruction
    assert draft_input["correspondence_type"] == LAST_DRAFT["correspondence_type"]


@pytest.mark.asyncio
async def test_a_message_with_no_last_draft_is_unaffected():
    """The zero-regression contract: a conversation with nothing to revise
    must resolve exactly as it did before draft_revision existed -- here, a
    short message with no document and no drafting phrase resolves to assist
    via the same short-message hint it always has, never touching the draft
    sub-graph at all."""
    graph, _document_analysis_graph, draft_graph, _routing_graph = _build_graph()
    config = {"configurable": {"thread_id": "revision-flow-2"}}

    result = await graph.ainvoke(
        {"input_text": "Kısalt.", "document_id": None, "last_draft": {}},
        config=config,
    )

    draft_graph.ainvoke.assert_not_called()
    assert result["plan_intent"] != "draft_revision"
