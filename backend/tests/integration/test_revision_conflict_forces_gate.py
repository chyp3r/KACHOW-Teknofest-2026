"""End-to-end proof that a revision instruction contradicting mevzuat/kaynak
is still applied in full and only *additionally* forces the human approval
gate -- never silently softened, rejected or reverted.

Follows test_revise_and_clarify_end_to_end.py's pattern: only the LLM-backed
sub-graphs are mocked; the revise sub-graph's conflict audit
(app.ai.revision.conflict) runs for real against a frozen legislation
context that does not cover the law the second turn's instruction cites.
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
async def test_an_unfounded_legislation_citation_is_applied_and_forces_the_gate(
    fake_llm, fake_fast_llm
):
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "conflict-gate-1"}}

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
    # it forced a pause for approval, not a rejection or a reverted edit.
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("human_gate",)
    assert second["final_output"]["status"] == "NEEDS_HUMAN_APPROVAL"
    payload = snapshot.tasks[0].interrupts[0].value
    assert "4982 sayılı Kanun" in payload["draft"]

    # ...and it is flagged, not silently accepted.
    conflicts = payload["conflicts"]
    assert conflicts
    assert any(c["kind"] == "mevzuat_dayanaksiz" for c in conflicts)
    assert payload["requires_human_approval"] is True
