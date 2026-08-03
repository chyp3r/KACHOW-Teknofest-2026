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
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.planning_graph import create_planning_graph

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


@pytest.mark.asyncio
async def test_a_placeholder_pauses_the_whole_orchestration_graph():
    graph, _mocks = _build_graph()
    config = {"configurable": {"thread_id": "hitl-test-1"}}

    result = await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

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
async def test_answering_resumes_without_regenerating_the_draft():
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

    snapshot = await graph.aget_state(config)
    assert not snapshot.next  # run completed; nothing left pending

    # The ~30s draft generation the executor already paid for before the
    # pause must never be repeated on resume.
    assert mocks["draft_graph"].ainvoke.await_count == 1
    assert mocks["routing_graph"].ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_a_still_missing_answer_pauses_again_instead_of_completing():
    """A blank answer leaves the placeholder unfilled -- the gate must ask
    again rather than shipping an incomplete draft."""
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
