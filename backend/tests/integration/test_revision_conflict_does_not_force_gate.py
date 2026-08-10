"""End-to-end proof that a revision instruction contradicting mevzuat/kaynak
is still applied in full, is reported to the user, and never pauses the run.

Was ``test_revision_conflict_forces_gate.py``, asserting the opposite of
this file's name: that a conflict finding forced the human-approval gate
open, indistinguishable from a genuine low-quality-draft pause. That
behaviour is gone -- ``ConflictReport.applied_anyway`` (see
``app.ai.revision.conflict``'s module docstring) is a hard invariant, and a
gate the user has to click through for a finding that changes nothing about
what already happened is exactly the kind of unnecessary blocking popup this
rewrite removes. A conflict is now advisory only: it never appears in
``PlanningState.draft_result["status"]``'s escalation, and is instead
published live as a non-blocking ``notice`` SSE event (see
``app.ai.workflows.events.emit_notice``), rendered by the frontend as its
own chat message rather than folded into the draft reply or a popup.

Follows ``test_revise_and_clarify_end_to_end.py``'s pattern: only the
LLM-backed sub-graphs are mocked; the revise sub-graph's conflict audit
(``app.ai.revision.conflict``) runs for real against a frozen legislation
context that does not cover the law the second turn's instruction cites.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.events import STATUS_QUEUE_KEY
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

#: Deliberately does not mention "4982" anywhere -- the second turn's
#: instruction citing "4982 sayılı Kanun" has nothing to ground it.
DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": DRAFT_TEXT,
    "correspondence_type": "response_letter",
    "combined_score": 85.0,
    "confidence_score": 85.0,
    "classification": {"summary": "Personel izin talebi."},
    "context": "[MEVZUAT] İlgili Yönetmelik Madde 5: ...",
    "source_document": "Sayı: 2026/1, Tarih: 01.01.2026, personel izin talebi.",
    "correspondence_type_source": "explicit",
    "style_examples": [],
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
async def test_an_unfounded_legislation_citation_is_applied_and_only_notices(
    fake_llm, fake_fast_llm
):
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    queue: asyncio.Queue = asyncio.Queue()
    config = {"configurable": {"thread_id": "conflict-notice-1", STATUS_QUEUE_KEY: queue}}

    first = await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )
    assert first["final_output"]["status"] == "COMPLETED"

    fake_llm.stream_chunks = [
        "4982 sayılı Kanun uyarınca bilgi edinme hakkı saklı kalmak kaydıyla arz ederim."
    ]
    second = await graph.ainvoke(
        {
            "input_text": "Kapanışı değiştir: 4982 sayılı Kanuna bir atıf ekle.",
            "document_id": None,
        },
        config=config,
    )

    # No second draft generation -- this went through revise, not draft.
    assert draft_graph.ainvoke.await_count == 1

    # The instruction was applied in full, not refused or softened --
    # and the run settled on its own, with no human-approval pause.
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ()
    assert second["final_output"]["status"] == "COMPLETED"
    assert "4982 sayılı Kanun" in second["final_output"]["draft"]["draft"]

    # ...and it is flagged, not silently accepted: the structured finding
    # is still attached to the draft result...
    conflicts = second["final_output"]["draft"]["conflicts"]
    assert conflicts
    assert any(c["kind"] == "mevzuat_dayanaksiz" for c in conflicts)
    assert second["final_output"]["draft"]["requires_human_approval"] is False

    # ...and reported live as its own non-blocking notice, never a popup.
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    notices = [event for event in events if event.get("event") == "notice"]
    assert notices, "expected a notice event for the conflict finding"
    assert "4982" in notices[0]["message"] or "4982" in notices[0]["title"]
    assert not any(event.get("event") == "interrupt" for event in events)
