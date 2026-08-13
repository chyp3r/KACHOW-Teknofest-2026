"""Proof that the writing brief's answers survive into a later revise turn.

The regression this guards against: DraftVersion carries classification/
context/source_document/style_examples forward so a revise turn can rebuild
the same grounding brief without re-resolving anything -- writing_brief
belongs on that same list. Without it, "3. paragrafı kısalt" on a draft
written for "KACMAK ekibi olarak" would drift back to an unstated,
institution-voiced draft the moment it got revised.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph

DRAFT_TEXT = (
    "Sayı: 2026/1\nTarih: 01.01.2026\nKonu: Yarışma Başvurusu\n\n"
    "Sayın Yarışma Komitesi,\n\n"
    "KACMAK ekibi olarak yarışmaya katılmak istediğimizi arz ederiz.\n\n"
    "Arz ederim.\n\nKACMAK Ekibi"
)

DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": DRAFT_TEXT,
    "correspondence_type": "response_letter",
    "combined_score": 88.0,
    "confidence_score": 88.0,
    "classification": {"summary": "Yarışma başvurusu."},
    "context": "",
    "source_document": "KACMAK ekibi olarak yarışmaya katılmak istiyoruz.",
    "requires_human_approval": False,
    "missing_information": [],
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
        # Echoes writing_brief back the way the real draft_graph does (it
        # flows through DraftState untouched -- see draft_graph.DraftState's
        # own docstring) -- this test's whole point is checking it survives.
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
    return graph, draft_graph


@pytest.mark.asyncio
async def test_writing_brief_answers_reach_the_reviser_on_a_later_revise_turn(
    fake_llm, fake_fast_llm
):
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "brief-into-revise"}}

    await graph.ainvoke(
        {
            "input_text": "KACMAK ekibi olarak yarışmaya katılmak için bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )

    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("brief_gate",)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["resolved"]["yazan_taraf"]["value"] == "KACMAK ekibi"

    from langgraph.types import Command

    answers = {
        question["key"]: ("Yarışma Komitesi" if question["key"] == "muhatap" else "__auto__")
        for question in payload["questions"]
    }
    result = await graph.ainvoke(
        Command(resume={"action": "answer", "answers": answers, "instructions": ""}),
        config=config,
    )
    assert result["final_output"]["status"] == "COMPLETED"

    snapshot_after_draft = await graph.aget_state(config)
    active_draft = snapshot_after_draft.values["focus"].active_draft
    assert active_draft.writing_brief.get("yazan_taraf") == "KACMAK ekibi"
    assert active_draft.writing_brief.get("muhatap") == "Yarışma Komitesi"

    fake_llm.stream_chunks = ["Saygılarımızla arz ederiz."]
    await graph.ainvoke(
        {"input_text": "Kapanışı 'Saygılarımızla arz ederiz.' yap.", "document_id": None},
        config=config,
    )

    snapshot_after_revise = await graph.aget_state(config)
    revised_draft = snapshot_after_revise.values["focus"].active_draft
    assert revised_draft.version == 2
    # The revise turn's own grounding brief still carries the same writing
    # brief forward -- see revise_graph._build_brief's "4. Yazım Briefi"
    # section, built from precisely this field.
    assert revised_draft.writing_brief.get("yazan_taraf") == "KACMAK ekibi"
    assert revised_draft.writing_brief.get("muhatap") == "Yarışma Komitesi"
