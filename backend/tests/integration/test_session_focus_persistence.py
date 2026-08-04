"""Proof that SessionFocus actually persists across turns.

Exercises the real compiled planning graph across two turns on the same
thread -- following test_hitl_flow.py's / test_memory_consolidation.py's
pattern (only the LLM-backed sub-graphs are mocked) -- and checks the
checkpointed `focus` channel directly. Unlike every other PlanningState
field, `planning_node` must never reset this one.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph

DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": "Sayın Makam, ... Arz ederim.",
    "correspondence_type": "cover_letter",
    "combined_score": 85.0,
    "confidence_score": 85.0,
}


def _build_graph(fake_llm, fake_fast_llm):
    document_analysis_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "document_type": "official_letter",
                "document_type_label": "Resmî Yazı",
                "summary": "Test evrakı.",
                "fields": {},
                "missing_fields": [],
                "compliance_status": "compliant",
                "mevzuat_suggestions": [],
            }
        )
    )
    draft_graph = AsyncMock(ainvoke=AsyncMock(return_value=dict(DRAFT_RESULT)))
    routing_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "routed_unit": "İnsan Kaynakları Daire Başkanlığı",
                "priority": "Normal",
                "reasoning": "Test gerekçesi.",
                "justification": "Test gerekçesi.",
            }
        )
    )
    graph = create_planning_graph(
        llm_client=fake_llm,
        document_analysis_graph=document_analysis_graph,
        rag_graph=AsyncMock(),
        draft_graph=draft_graph,
        routing_graph=routing_graph,
        fast_llm_client=fake_fast_llm,
        checkpointer=MemorySaver(),
    )
    return graph


@pytest.mark.asyncio
async def test_the_objective_accumulates_and_the_active_draft_survives_across_turns(
    fake_llm, fake_fast_llm
):
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "focus-persistence-test"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )
    snapshot_after_first = await graph.aget_state(config)
    focus_after_first = snapshot_after_first.values["focus"]

    assert focus_after_first.objective == "Bu evraka cevap yazısı hazırla."
    assert focus_after_first.active_draft is not None
    assert focus_after_first.active_draft.version == 1
    assert focus_after_first.active_draft.created_from == "draft"

    await graph.ainvoke(
        {"input_text": "Şimdi de başka bir evraka taslak hazırla.", "document_id": None},
        config=config,
    )
    snapshot_after_second = await graph.aget_state(config)
    focus_after_second = snapshot_after_second.values["focus"]

    # Accumulated, not replaced -- both turns' contributions are present.
    assert "Bu evraka cevap yazısı hazırla." in focus_after_second.objective
    assert "Şimdi de başka bir evraka taslak hazırla." in focus_after_second.objective

    # A second settled draft becomes version 2 -- keyed off which step
    # produced it (draft, again, both times here), not inferred from "a
    # draft already existed" -- and the first version is still in the
    # history rather than overwritten. See test_revise_flow.py for the
    # actual revise step's own versioning.
    assert focus_after_second.active_draft.version == 2
    assert focus_after_second.active_draft.created_from == "draft"
    assert len(focus_after_second.draft_history) == 2
    assert focus_after_second.draft_history[0].version == 1


@pytest.mark.asyncio
async def test_a_conversational_turn_does_not_reset_a_prior_draft_s_focus(
    fake_llm, fake_fast_llm
):
    fake_llm.stream_chunks = ["merhaba"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "focus-persistence-chat-does-not-reset"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )
    await graph.ainvoke({"input_text": "Merhaba", "document_id": None}, config=config)

    snapshot = await graph.aget_state(config)
    focus = snapshot.values["focus"]

    # planning_node resets every turn-scoped *_result field, but focus is
    # not one of them -- a plain chat turn must not erase the active draft.
    assert focus.active_draft is not None
    assert focus.active_draft.version == 1
    assert focus.last_intent == "assist"
