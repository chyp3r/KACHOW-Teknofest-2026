"""End-to-end proof of the revise and clarify flows through the real graph.

Follows test_hitl_flow.py's pattern: only document_analysis_graph/draft_graph/
routing_graph are mocked (a chat-intent or revise-intent turn never touches
them once a draft already exists), everything else -- routing, the revise
step's own deterministic parse/locate/merge, the checkpointer round-trip --
runs for real.

This is the scenario the whole SessionFocus/revise/clarify design exists
for: "taslak hazırla" -> "3. paragrafı daha resmi yap" resolves as a single,
cheap, targeted revision of the same draft rather than a fresh one, and a
genuinely ambiguous, expensive-to-guess-wrong follow-up gets a question
instead of a guess.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph

DRAFT_TEXT = (
    "Sayı: 2026/1\n"
    "Tarih: 01.01.2026\n"
    "Konu: Personel İzin Talebi\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": DRAFT_TEXT,
    "correspondence_type": "response_letter",
    "combined_score": 85.0,
    "confidence_score": 85.0,
    "classification": {"summary": "Personel izin talebi."},
    "context": "[MEVZUAT] İlgili Yönetmelik Madde 5: ...",
    "source_document": "Sayı: 2026/1, Tarih: 01.01.2026, personel izin talebi.",
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
    return graph, draft_graph


@pytest.mark.asyncio
async def test_a_targeted_revise_never_reruns_the_draft_pipeline(fake_llm, fake_fast_llm):
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "revise-e2e"}}

    first = await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )
    assert first["final_output"]["draft"]["draft"] == DRAFT_TEXT
    assert draft_graph.ainvoke.await_count == 1

    fake_llm.stream_chunks = ["Bilgilerinize sunulur."]
    second = await graph.ainvoke(
        {"input_text": "Kapanışı değiştir: 'Bilgilerinize sunulur.' yaz.", "document_id": None},
        config=config,
    )

    # The single-call revise flow ran instead -- the (expensive, multi-call)
    # draft pipeline was never touched a second time.
    assert draft_graph.ainvoke.await_count == 1

    revised_draft = second["final_output"]["draft"]["draft"]
    assert "Bilgilerinize sunulur." in revised_draft
    # Everything outside the closing survives untouched.
    assert "Konu: Personel İzin Talebi" in revised_draft
    assert "İlgi yazı kapsamında personelimizin izin talebi" in revised_draft
    assert "Ali Veli" in revised_draft

    snapshot = await graph.aget_state(config)
    focus = snapshot.values["focus"]
    assert focus.active_draft.version == 2
    assert focus.active_draft.created_from == "revise"
    assert focus.active_draft.text == revised_draft
    assert len(focus.draft_history) == 2


@pytest.mark.asyncio
async def test_an_ambiguous_expensive_followup_asks_instead_of_guessing(fake_llm, fake_fast_llm):
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "clarify-e2e"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )

    result = await graph.ainvoke({"input_text": "Kısalt.", "document_id": None}, config=config)

    # No second draft/revise generation happened -- the system asked instead.
    assert draft_graph.ainvoke.await_count == 1
    assert result["final_output"]["status"] != "FAILED"
    reply = result["final_output"]["assist"]["reply"]
    assert reply  # a real question was produced, not a silent guess

    snapshot = await graph.aget_state(config)
    assert snapshot.values["focus"].pending_clarification is not None

    # A short affirmative now resolves the open question directly, without
    # falling through the ladder or the model.
    fake_llm.stream_chunks = ["Taslak kısaltıldı."]
    followup = await graph.ainvoke({"input_text": "evet", "document_id": None}, config=config)

    snapshot_after = await graph.aget_state(config)
    assert snapshot_after.values["focus"].pending_clarification is None
    assert followup["final_output"]["status"] != "FAILED"
