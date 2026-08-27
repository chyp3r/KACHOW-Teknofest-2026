"""#282: a placeholder answered (or deferred with "Sen karar ver") at the
draft-turn missing-information gate must not be re-asked on a later revise
turn.

The draft-side half of that guarantee is proven here: the gate answers --
including the AUTO_ANSWER sentinel for a deferred field -- land on
``focus.active_draft.resolved_placeholder_answers`` so the next revise turn
can read them. The revise-side half (build_missing_info_request skipping
those keys, the writing-brief pre-fill) is covered in
``tests/unit/ai/test_revise_graph.py``.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.workflows.planning_graph import create_planning_graph
from app.ai.workflows.writing_brief import AUTO_ANSWER

DRAFT_TEXT = (
    "Sayı: [Belge Sayısı]\nTarih: 01.01.2026\nKonu: Yarışma Başvurusu\n\n"
    "Sayın Yarışma Komitesi,\n\n"
    "KACMAK ekibi olarak yarışmaya katılmak istediğimizi arz ederiz.\n\n"
    "Arz ederim.\n\n[İmza sahibi]"
)

MISSING_INFO = [
    {"key": "belge_sayisi", "label": "Belge Sayısı"},
    {"key": "imza_sahibi", "label": "İmza sahibi"},
]

DRAFT_RESULT = {
    "status": "NEEDS_INPUT",
    "draft": DRAFT_TEXT,
    "correspondence_type": "response_letter",
    "combined_score": 70.0,
    "confidence_score": 70.0,
    "classification": {"summary": "Yarışma başvurusu.", "missing_fields": []},
    "context": "",
    "source_document": "KACMAK ekibi olarak yarışmaya katılmak istiyoruz.",
    "requires_human_approval": True,
    "missing_information": MISSING_INFO,
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

    async def _draft_ainvoke(call_state, **_kwargs):
        return {**DRAFT_RESULT, "writing_brief": call_state.get("writing_brief") or {}}

    draft_graph = AsyncMock(ainvoke=AsyncMock(side_effect=_draft_ainvoke))
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
async def test_gate_answers_and_deferrals_persist_onto_the_active_draft(fake_llm, fake_fast_llm):
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "gate-answers-persist"}}

    await graph.ainvoke(
        {
            "input_text": "KACMAK ekibi olarak yarışmaya katılmak için bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )

    # First interrupt: the pre-draft writing brief.
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("brief_gate",)
    brief_payload = snapshot.tasks[0].interrupts[0].value
    brief_answers = {q["key"]: "__auto__" for q in brief_payload["questions"]}
    await graph.ainvoke(
        Command(resume={"action": "answer", "answers": brief_answers, "instructions": ""}),
        config=config,
    )

    # Second interrupt: the missing-information gate.
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("human_gate",)

    await graph.ainvoke(
        Command(
            resume={
                "action": "answer",
                "answers": {"belge_sayisi": "E-2026/42", "imza_sahibi": AUTO_ANSWER},
            }
        ),
        config=config,
    )

    snapshot = await graph.aget_state(config)
    active_draft = snapshot.values["focus"].active_draft
    assert active_draft.resolved_placeholder_answers == {
        "belge_sayisi": "E-2026/42",
        "imza_sahibi": AUTO_ANSWER,
    }
    # The real answer was spliced in; the deferred one stays as a visible
    # placeholder (same convention as the draft flow's AUTO_ANSWER path).
    assert "[Belge Sayısı]" not in active_draft.text
    assert "E-2026/42" in active_draft.text
    assert "[İmza sahibi]" in active_draft.text
