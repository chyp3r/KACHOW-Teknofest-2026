"""End-to-end proof that the human approval gate's "revizyon iste" action
actually revises the draft within the same run, instead of discarding it.

Before this, `human_gate_node`'s "revise" action only appended the human's
note to `draft_result["instructions"]` and ended the turn with status
REVISE_REQUESTED -- a status `planning_node` reset every turn and
`_VERSIONABLE_DRAFT_STATUSES` never versioned, so the draft (and the note)
were both silently lost and the frontend's "Revizyon iste" button did
nothing but say "reddedildi". Follows test_hitl_flow.py's and
test_revise_and_clarify_end_to_end.py's pattern: only the LLM-backed
sub-graphs (document analysis, draft, routing) are mocked; the gate, the
revise sub-graph, and the checkpointer round-trip all run for real.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings

SOURCE_DOCUMENT = "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak."

WELL_FORMED_DRAFT = (
    "Konu: Test Konusu\nSayı: E-1-1\nTarih: 30.07.2026\n\n"
    "Sayın Makam,\n\nİlgi yazı kapsamında bilgi arz olunur.\n\n"
    "Arz ederim.\n\nAli Veli\nGenel Müdür"
)

#: Missing "Konu:" on purpose -- STRUCTURE_CHECKS always reports it, so any
#: draft shaped like this always requires human approval regardless of what
#: the (fixed) fake stream returns, letting the round-cap test force
#: `route_after_gate_revise` back to the gate every single round.
STRUCTURALLY_INCOMPLETE_DRAFT = (
    "Sayın Makam,\n\nİlgi yazı kapsamında bilgi arz olunur.\n\n"
    "Arz ederim.\n\nAli Veli\nGenel Müdür"
)

MOCK_DRAFT_RESULT = {
    "status": "NEEDS_HUMAN_APPROVAL",
    "draft": WELL_FORMED_DRAFT,
    "missing_information": [],
    "confidence_score": 60.0,
    "combined_score": 60.0,
    "requires_human_approval": True,
    "verification": {},
    "judge": {},
    "source_document": SOURCE_DOCUMENT,
    "context": "İlgili mevzuat bağlamı.",
    "classification": {},
    "instructions": "",
    "correspondence_type": "cover_letter",
    "correspondence_type_source": "explicit",
    "style_examples": [],
}


def _build_graph(fake_llm, fake_fast_llm, *, draft_result=None):
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
    draft_graph = AsyncMock(
        ainvoke=AsyncMock(return_value=dict(draft_result or MOCK_DRAFT_RESULT))
    )
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
    return graph, {"draft_graph": draft_graph, "routing_graph": routing_graph}


@pytest.mark.asyncio
async def test_revizyon_iste_produces_a_new_draft_in_the_same_run(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "gate-revise-1"}}

    first = await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )
    assert not first.get("final_output")
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("human_gate",)

    fake_llm.stream_chunks = ["Bilgilerinize sunulur."]
    second = await graph.ainvoke(
        Command(
            resume={
                "action": "revise",
                "answers": {},
                "instructions": "Kapanışı 'Bilgilerinize sunulur.' yap.",
            }
        ),
        config=config,
    )

    # The gate's own revise loop, not a second draft generation.
    assert mocks["draft_graph"].ainvoke.await_count == 1
    assert second["final_output"]["status"] != "FAILED"
    revised = second["final_output"]["draft"]["draft"]
    assert "Bilgilerinize sunulur." in revised
    assert "İlgi yazı kapsamında bilgi arz olunur." in revised  # untouched paragraph survives

    snapshot_after = await graph.aget_state(config)
    focus = snapshot_after.values["focus"]
    assert focus.active_draft is not None
    assert focus.active_draft.text == revised
    assert focus.active_draft.created_from == "gate_revise"
    # One version, not two: the whole draft -> gate -> revise sequence is a
    # single turn (no fresh input_text in between) -- focus_node runs once,
    # at the true end of the turn, and records the turn's final settled
    # text, not every intermediate gate round (see focus_node's docstring).
    assert len(focus.draft_history) == 1
    assert not snapshot_after.next  # the run actually finished, not stuck re-pausing


@pytest.mark.asyncio
async def test_the_revision_round_cap_ends_the_turn_without_losing_the_last_draft(
    fake_llm, fake_fast_llm, monkeypatch
):
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)
    draft_result = {**MOCK_DRAFT_RESULT, "draft": STRUCTURALLY_INCOMPLETE_DRAFT}
    graph, mocks = _build_graph(fake_llm, fake_fast_llm, draft_result=draft_result)
    config = {"configurable": {"thread_id": "gate-revise-cap"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )

    fake_llm.stream_chunks = ["Sayın Makam,\n\nGüncellenmiş içerik.\n\nArz ederim.\n\nAli Veli\nGenel Müdür"]
    seen_interrupt_ids = []
    last_result = None
    for _ in range(settings.HITL_MAX_GATE_REVISIONS + 1):
        last_result = await graph.ainvoke(
            Command(resume={"action": "revise", "answers": {}, "instructions": "Tekrar düzenle."}),
            config=config,
        )
        snapshot = await graph.aget_state(config)
        if snapshot.next:
            seen_interrupt_ids.append(snapshot.tasks[0].interrupts[0].value)

    # Every round the loop actually paused for got a distinct interrupt --
    # without gate_revision_count in the hash, a re-pause on identical text
    # would dedup away on the frontend and the run would hang.
    assert len(seen_interrupt_ids) == settings.HITL_MAX_GATE_REVISIONS

    # The (cap + 1)-th click ended the turn instead of looping forever.
    assert last_result.get("final_output")
    snapshot = await graph.aget_state(config)
    assert not snapshot.next

    focus = snapshot.values["focus"]
    # One version for the whole turn (see the same-turn note in the test
    # above) -- but it is the *last* successful gate_revise round's real
    # text, not lost just because the loop never converged to an
    # auto-approved draft.
    assert len(focus.draft_history) == 1
    assert focus.active_draft is not None
    assert focus.active_draft.text  # real text, not blank/discarded
    assert mocks["draft_graph"].ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_reddet_captures_a_reason_and_archives_the_draft(fake_llm, fake_fast_llm):
    graph, _mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "gate-reject-1"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla.", "document_id": None}, config=config
    )

    result = await graph.ainvoke(
        Command(resume={"action": "reject", "answers": {}, "reason": "Üslup çok resmi değil."}),
        config=config,
    )

    assert result["final_output"]["draft"]["status"] == "REJECTED"
    assert result["final_output"]["draft"]["rejection_reason"] == "Üslup çok resmi değil."

    snapshot = await graph.aget_state(config)
    focus = snapshot.values["focus"]
    assert focus.active_draft is None
    assert focus.draft_history[-1].created_from == "rejected"
    assert focus.draft_history[-1].rejection_reason == "Üslup çok resmi değil."
    assert focus.last_rejection["reason"] == "Üslup çok resmi değil."
