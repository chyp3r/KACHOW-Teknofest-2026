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
app.ai.workflows.writing_brief) fires before the missing_information gate
this file actually tests. Three of the four tests disable it
(`HITL_BRIEF_GATE_ENABLED=False`) since they are about the missing-info
gate, not this one; the first resumes the brief gate first with "Sen karar
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
from app.observability.ai_metrics import HITL_INTERRUPTS

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


def _build_graph(llm_client=None, fast_llm_client=None):
    """Returns (compiled_graph, sub_graph_mocks) so tests can assert on
    call counts -- e.g. that draft_graph.ainvoke() runs exactly once across
    a pause and its resume, never repeating the ~30s generation.

    ``llm_client``/``fast_llm_client`` default to a bare ``MagicMock`` --
    fine for every test in this file except the one exercising the
    missing_information gate's "revise" escape hatch, which runs the real
    revise sub-graph and needs a fixture that actually behaves like a
    streaming client (see the ``fake_llm``/``fake_fast_llm`` fixtures).
    """
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
        llm_client=llm_client or MagicMock(spec=BaseLLMClient),
        fast_llm_client=fast_llm_client,
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
    before = HITL_INTERRUPTS.labels(kind="missing_information")._value.get()

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

    result = await graph.ainvoke(
        Command(resume={"action": "answer", "answers": {"muhatap": "İlgili Makama"}, "instructions": ""}),
        config=config,
    )

    # C25: interrupt() replays everything before it on resume, including a
    # counter placed there -- one real pause-and-answer cycle must count
    # once, not twice (a naive placement fires on both the pausing call and
    # the resuming replay).
    assert HITL_INTERRUPTS.labels(kind="missing_information")._value.get() == before + 1

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
    # C1 regression: this second NEEDS_INPUT round must be hashed
    # differently from the first (the draft text and current_step_idx are
    # identical across both -- see human_gate_node's own interrupt_id
    # comment) or the frontend's interrupt_id dedup silently drops the
    # repeat event and the session hangs. needs_input_round is the state
    # field that makes the two rounds' hashes differ.
    assert snapshot.values["needs_input_round"] == 1


@pytest.mark.asyncio
async def test_rejecting_at_the_missing_information_gate_ends_the_turn_cleanly(monkeypatch):
    """C1 regression: "Vazgeç" (action="reject") used to fall straight
    through to apply_answers with an empty answers dict -- every placeholder
    came back unfilled, the draft text was unchanged, and the resulting
    NEEDS_INPUT round hashed identically to the round the user was trying to
    leave. The frontend's interrupt_id dedup silently dropped it and the
    session hung with no way to send another message on that thread. reject
    must end the turn (StepStatus.REJECTED), not reopen the gate."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    graph, _mocks = _build_graph()
    config = {"configurable": {"thread_id": "hitl-reject-1"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )
    result = await graph.ainvoke(
        Command(resume={"action": "reject", "answers": {}, "instructions": "", "reason": "Vazgeçtim."}),
        config=config,
    )

    assert result["final_output"]["status"] == "REJECTED"
    assert result["final_output"]["draft"]["rejection_reason"] == "Vazgeçtim."

    # The run must not still be paused -- the whole point of the fix is
    # that a subsequent message on this thread is not refused.
    snapshot = await graph.aget_state(config)
    assert not snapshot.next


@pytest.mark.asyncio
async def test_a_revision_note_in_the_answer_box_runs_revise_instead_of_being_substituted_in(
    fake_llm, fake_fast_llm, monkeypatch
):
    """The bug this guards against: typing a revision instruction into the
    missing-information answer box used to be treated as the literal answer
    to the pending placeholder -- apply_answers would substitute it verbatim
    into [MUHATAP], producing a nonsense draft. The frontend's escape hatch
    sends action="revise" instead of "answer"; this must run a real revision
    (reusing the same gate_revise machinery the missing-information gate's
    own "revizyon iste" already runs through), not apply_answers."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "hitl-revise-escape-hatch"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

    fake_llm.stream_chunks = [DRAFT_WITH_PLACEHOLDER.replace("Genel Müdür", "Daire Başkanı")]
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "revise",
                "answers": {},
                "instructions": "Unvanı Daire Başkanı olarak değiştir.",
            }
        ),
        config=config,
    )

    # The draft pipeline never ran a second time -- the note went through
    # revise, not a fresh draft.
    assert mocks["draft_graph"].ainvoke.await_count == 1
    revised_draft = (
        result.get("final_output", {}).get("draft", {}).get("draft")
        or (await graph.aget_state(config)).values["draft_result"]["draft"]
    )
    # The placeholder text was never treated as an answer -- it is either
    # still there (reviser left it alone, per reviser.md's own rule) or the
    # gate is asking about it again, but it must never contain the literal
    # revision note as if it were a muhatap value.
    assert "Unvanı Daire Başkanı olarak değiştir" not in revised_draft
    assert "Daire Başkanı" in revised_draft


@pytest.mark.asyncio
async def test_the_revise_escape_hatch_carries_the_sub_genre_and_status_through(
    fake_llm, fake_fast_llm, monkeypatch
):
    """C15: gate_revise_node used to build its DraftVersion without
    correspondence_sub_genre/status/rejection_reason, silently dropping
    them on every gate-triggered revision -- a revision of a specific
    sub-genre (an itiraz dilekçesi, say) fell back to generic "diğer resmî
    yazışma" phrasing, and a revision of a REJECTED draft never saw
    _build_brief's own rejection-reason section."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)
    draft_result = {**MOCK_DRAFT_RESULT, "correspondence_sub_genre": "itiraz dilekçesi"}
    document_analysis_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "document_type": "official_letter", "document_type_label": "Resmî Yazı",
                "summary": "Test evrakı.", "fields": {}, "missing_fields": [],
                "compliance_status": "compliant", "mevzuat_suggestions": [],
            }
        )
    )
    draft_graph = AsyncMock(ainvoke=AsyncMock(return_value=dict(draft_result)))
    routing_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "routed_unit": "İnsan Kaynakları Daire Başkanlığı", "priority": "Normal",
                "reasoning": "Test gerekçesi.", "justification": "Test gerekçesi.",
            }
        )
    )
    graph = create_planning_graph(
        llm_client=fake_llm, fast_llm_client=fake_fast_llm,
        document_analysis_graph=document_analysis_graph, rag_graph=AsyncMock(),
        draft_graph=draft_graph, routing_graph=routing_graph, checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": "hitl-sub-genre-passthrough"}}

    await graph.ainvoke(
        {"input_text": "Bu evraka cevap yazısı hazırla", "document_id": None}, config=config
    )

    fake_llm.stream_chunks = [DRAFT_WITH_PLACEHOLDER.replace("Genel Müdür", "Daire Başkanı")]
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "revise", "answers": {},
                "instructions": "Unvanı Daire Başkanı olarak değiştir.",
            }
        ),
        config=config,
    )

    assert (
        result.get("final_output", {}).get("draft", {}).get("correspondence_sub_genre")
        == "itiraz dilekçesi"
    )
