"""End-to-end proof of the pre-draft writing-brief gate (see
app.ai.workflows.writing_brief).

Follows test_hitl_flow.py's pattern: only the LLM-backed sub-graphs
(document analysis, draft, routing) are mocked; the brief step's
deterministic resolution, the gate itself, and the checkpointer round-trip
all run for real.

The whole point of the gate is that the ~30s draft generation never runs
until the writing brief is settled -- every test here that pauses asserts
draft_graph.ainvoke was never called while paused, the direct analogue of
test_hitl_flow.py's "never regenerate" assertion for the approval gate.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.workflows.events import STATUS_QUEUE_KEY
from app.ai.workflows.planning_graph import create_planning_graph

DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": "Sayın Makam, ... Arz ederim.",
    "correspondence_type": "cover_letter",
    "combined_score": 90.0,
    "confidence_score": 90.0,
    "requires_human_approval": False,
    "missing_information": [],
}


def _build_graph(fake_llm, fake_fast_llm, *, fields=None):
    document_analysis_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "document_type": "official_letter",
                "document_type_label": "Resmî Yazı",
                "summary": "Test evrakı.",
                "fields": fields or {},
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
    return graph, {"draft_graph": draft_graph, "routing_graph": routing_graph}


@pytest.mark.asyncio
async def test_the_draft_pipeline_never_runs_while_the_brief_gate_is_paused(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "brief-gate-1"}}

    result = await graph.ainvoke(
        {
            "input_text": "Yarışmaya katılım şartlarını öğrenmek için KACMAK ekibi olarak bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )

    assert not result.get("final_output")
    assert mocks["draft_graph"].ainvoke.await_count == 0

    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("brief_gate",)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["kind"] == "writing_brief"
    assert payload["resolved"]["yazan_taraf"]["value"] == "KACMAK ekibi"
    # muhatap is the one thing this turn's message doesn't answer.
    assert any(question["key"] == "muhatap" for question in payload["questions"])
    # imza/sayi default silently to "Sen karar ver" (see
    # resolve_brief) -- they must never show up in the "Bilinenler" strip
    # as if they were a resolved fact rather than an unasked default.
    assert "imza" not in payload["resolved"]
    assert "sayi" not in payload["resolved"]


@pytest.mark.asyncio
async def test_resuming_with_answers_runs_the_draft_exactly_once_carrying_them_forward(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "brief-gate-2"}}

    await graph.ainvoke(
        {
            "input_text": "Yarışmaya katılım şartlarını öğrenmek için KACMAK ekibi olarak bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )
    result = await graph.ainvoke(
        Command(
            resume={
                "action": "answer",
                "answers": {"muhatap": "TEKNOFEST Yarışma Komitesi", "kapanis": "__auto__"},
                "instructions": "",
            }
        ),
        config=config,
    )

    assert mocks["draft_graph"].ainvoke.await_count == 1
    call_kwargs = mocks["draft_graph"].ainvoke.await_args.args[0]
    assert call_kwargs["writing_brief"]["yazan_taraf"] == "KACMAK ekibi"
    assert call_kwargs["writing_brief"]["muhatap"] == "TEKNOFEST Yarışma Komitesi"
    assert result["final_output"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_a_blank_required_answer_re_asks_with_a_different_interrupt_id(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    queue: asyncio.Queue = asyncio.Queue()
    config = {"configurable": {"thread_id": "brief-gate-3", STATUS_QUEUE_KEY: queue}}

    def _interrupt_ids() -> list[str]:
        ids = []
        while not queue.empty():
            event = queue.get_nowait()
            if event.get("event") == "interrupt":
                ids.append(event["interrupt_id"])
        return ids

    await graph.ainvoke(
        {
            "input_text": "Yarışmaya katılım şartlarını öğrenmek için KACMAK ekibi olarak bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )
    first_interrupt_id = _interrupt_ids()[-1]

    await graph.ainvoke(
        Command(resume={"action": "answer", "answers": {"muhatap": ""}, "instructions": ""}),
        config=config,
    )
    second_interrupt_id = _interrupt_ids()[-1]

    assert second_interrupt_id != first_interrupt_id

    second_snapshot = await graph.aget_state(config)
    assert second_snapshot.next == ("brief_gate",)
    assert mocks["draft_graph"].ainvoke.await_count == 0


@pytest.mark.asyncio
async def test_rejecting_the_brief_gate_ends_the_turn_without_a_draft(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "brief-gate-4"}}

    await graph.ainvoke(
        {
            "input_text": "Yarışmaya katılım şartlarını öğrenmek için KACMAK ekibi olarak bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )
    result = await graph.ainvoke(
        Command(resume={"action": "reject", "answers": {}, "instructions": ""}), config=config
    )

    assert mocks["draft_graph"].ainvoke.await_count == 0
    assert result["final_output"]["draft"]["status"] == "SKIPPED"
    snapshot = await graph.aget_state(config)
    assert not snapshot.next


@pytest.mark.asyncio
async def test_a_fully_determined_turn_never_pauses_at_the_brief_gate(fake_llm, fake_fast_llm):
    graph, mocks = _build_graph(
        fake_llm, fake_fast_llm,
        fields={"gonderen_kurum": "TEKNOFEST Bilişim Vadisi", "muhatap": "KACMAK Ekibi"}
    )
    config = {"configurable": {"thread_id": "brief-gate-5"}}

    result = await graph.ainvoke(
        {
            "input_text": "KACMAK ekibi olarak arz ederim şeklinde bir cevap yazısı hazırla",
            "document_id": None,
        },
        config=config,
    )

    assert result["final_output"]["status"] == "COMPLETED"
    assert mocks["draft_graph"].ainvoke.await_count == 1
    snapshot = await graph.aget_state(config)
    assert not snapshot.next
