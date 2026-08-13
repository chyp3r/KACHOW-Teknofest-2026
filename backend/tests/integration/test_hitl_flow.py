"""End-to-end interrupt/resume test for the human-in-the-loop gate.

Exercises the actual compiled planning graph -- routing, the human_gate node,
the deterministic verifier, checkpointer-backed pause/resume -- with only the
LLM-backed sub-graphs (document analysis, drafting, routing) replaced by
mocks, since standing up real models has no place in a unit/integration
suite. Uses MemorySaver rather than AsyncPostgresSaver so this runs without a
database, in CI.

This is the requirement Görev 2 hinges on: "gerekli durumlarda eksik bilgi
talep edebilmesi" -- a draft that leaves a placeholder pauses the whole
orchestration graph rather than silently shipping an incomplete letter, and
answering it does not re-run the ~30s draft generation.

Every turn here starts a document-less "draft" plan with an empty
classification (`fields: {}`), which today also means every writing-brief
slot is unresolved -- the pre-draft brief_gate (see
app.ai.workflows.writing_brief) fires before the missing_information/
draft_approval gate this file actually tests. Two of the three tests disable
it (`HITL_BRIEF_GATE_ENABLED=False`) since they are about the missing-info
gate, not this one; the third resumes the brief gate first with "Sen karar
ver" answers, which is also the composability proof that two gates can
chain within a single turn.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings

SOURCE_DOCUMENT = "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak."

DRAFT_WITH_PLACEHOLDER = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın [MUHATAP],\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

MOCK_DRAFT_RESULT = {
    "status": "NEEDS_INPUT",
    "draft": DRAFT_WITH_PLACEHOLDER,
    "missing_information": [
        {"key": "muhatap", "label": "MUHATAP", "why": "", "example": None, "required": True}
    ],
    "confidence_score": 40.0,
    "combined_score": 40.0,
    "requires_human_approval": True,
    "verification": {},
    "judge": {},
    "source_document": SOURCE_DOCUMENT,
    "context": "İlgili mevzuat bağlamı.",
    "classification": {},
    "instructions": "",
    "correspondence_type": "cover_letter",
}


def _build_graph():
    """Returns (compiled_graph, sub_graph_mocks) so tests can assert on
    call counts -- e.g. that draft_graph.ainvoke() runs exactly once across
    a pause and its resume, never repeating the ~30s generation."""
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
    rag_graph = AsyncMock()
    draft_graph = AsyncMock(ainvoke=AsyncMock(return_value=dict(MOCK_DRAFT_RESULT)))
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
        llm_client=MagicMock(spec=BaseLLMClient),
        document_analysis_graph=document_analysis_graph,
        rag_graph=rag_graph,
        draft_graph=draft_graph,
        routing_graph=routing_graph,
        checkpointer=MemorySaver(),
    )
    mocks = {
        "document_analysis_graph": document_analysis_graph,
        "rag_graph": rag_graph,
        "draft_graph": draft_graph,
        "routing_graph": routing_graph,
    }
    return graph, mocks


async def _resolve_brief_gate_with_defaults(graph, config):
    """Resume a paused brief_gate with "Sen karar ver" for every question.

    Shared by every test in this file that doesn't itself want to exercise
    the brief gate -- their input classification has empty `fields`, so
    every writing-brief slot is unresolved and the gate always opens first.
    """
    snapshot = await graph.aget_state(config)
    if snapshot.next != ("brief_gate",):
        return None
    payload = snapshot.tasks[0].interrupts[0].value
    answers = {question["key"]: "__auto__" for question in payload["questions"]}
    return await graph.ainvoke(
        Command(resume={"action": "answer", "answers": answers, "instructions": ""}),
        config=config,
    )


@pytest.mark.asyncio
async def test_a_placeholder_pauses_the_whole_orchestration_graph():
    graph, _mocks = _build_graph()
    config = {"configurable": {"thread_id": "hitl-test-1"}}

    result = await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

    # The run paused at the pre-draft writing brief -- the same "no
    # classification fields, nothing resolved" turn shape means every slot
    # is unknown. Resolving it (with "Sen karar ver" for every slot) is
    # what proves the two gates compose within a single turn.
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("brief_gate",)
    result = await _resolve_brief_gate_with_defaults(graph, config)

    # The run paused rather than completing: no final_output was compiled.
    assert not result.get("final_output")

    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("human_gate",)

    interrupts = snapshot.tasks[0].interrupts
    assert len(interrupts) == 1
    payload = interrupts[0].value
    assert payload["kind"] == "missing_information"
    assert payload["questions"][0]["key"] == "muhatap"


@pytest.mark.asyncio
async def test_answering_resumes_without_regenerating_the_draft(monkeypatch):
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    graph, mocks = _build_graph()
    config = {"configurable": {"thread_id": "hitl-test-2"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

    result = await graph.ainvoke(
        Command(resume={"action": "answer", "answers": {"muhatap": "İlgili Makama"}, "instructions": ""}),
        config=config,
    )

    assert result["final_output"]["status"] == "COMPLETED"
    assert "İlgili Makama" in result["final_output"]["draft"]["draft"]
    assert "[MUHATAP]" not in result["final_output"]["draft"]["draft"]
    assert result["final_output"]["routing"]["routed_unit"] == "İnsan Kaynakları Daire Başkanlığı"

    # plan_steps/intent must survive the human_gate pause+resume so the
    # frontend can rebuild the workflow stepper for a session reopened from
    # history, where only the persisted final_output is available (not the
    # live SSE stream that produced it).
    assert result["final_output"]["plan_steps"]
    assert "draft" in result["final_output"]["plan_steps"]
    assert result["final_output"]["intent"] == "draft"

    snapshot = await graph.aget_state(config)
    assert not snapshot.next  # run completed; nothing left pending

    # The ~30s draft generation the executor already paid for before the
    # pause must never be repeated on resume.
    assert mocks["draft_graph"].ainvoke.await_count == 1
    assert mocks["routing_graph"].ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_a_still_missing_answer_pauses_again_instead_of_completing(monkeypatch):
    """A blank answer leaves the placeholder unfilled -- the gate must ask
    again rather than shipping an incomplete draft."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    graph, mocks = _build_graph()
    config = {"configurable": {"thread_id": "hitl-test-4"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )
    result = await graph.ainvoke(
        Command(resume={"action": "answer", "answers": {}, "instructions": ""}), config=config
    )

    assert not result.get("final_output")
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("human_gate",)
    assert "[MUHATAP]" in snapshot.values["draft_result"]["draft"]
