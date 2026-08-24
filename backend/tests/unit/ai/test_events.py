"""Unit tests for the SSE progress-event publishing helpers."""

import asyncio

import pytest

from app.ai.workflows.events import (
    child_config,
    emit_guardrail_event,
    emit_interrupt,
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_partial,
    emit_reply_stream,
    emit_token,
    get_status_queue,
)


def _config(queue: "asyncio.Queue | None" = None) -> dict:
    if queue is None:
        return {}
    return {"configurable": {"status_queue": queue}}


def test_get_status_queue_returns_none_for_missing_config():
    assert get_status_queue(None) is None
    assert get_status_queue({}) is None
    assert get_status_queue({"configurable": {}}) is None


@pytest.mark.asyncio
async def test_emit_is_a_no_op_without_a_queue():
    """Non-streaming callers (document upload, tests, evals) run the same
    graphs with no queue attached; every emit call must be harmless there."""
    await emit_node_start(None, "draft", "Taslak", "başladı")
    await emit_node_start({}, "draft", "Taslak", "başladı")


@pytest.mark.asyncio
async def test_node_start_and_end_carry_the_expected_shape():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_node_start(config, "draft", "Taslak", "Taslak üretiliyor...")
    await emit_node_end(config, "draft", "Taslak", "Tamamlandı.", {"draft": "metin"})

    start = queue.get_nowait()
    end = queue.get_nowait()

    assert start == {
        "event": "node_start", "node": "draft", "label": "Taslak",
        "message": "Taslak üretiliyor...", "meta": {}, "seq": 1,
    }
    assert end == {
        "event": "node_end", "node": "draft", "label": "Taslak",
        "message": "Tamamlandı.", "result": {"draft": "metin"}, "meta": {}, "seq": 2,
    }


@pytest.mark.asyncio
async def test_node_start_meta_survives_a_second_draft_attempt():
    """A revision attempt reuses the 'draft' node id; meta.attempt is what the
    frontend uses to clear stale streamed text rather than concatenating."""
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_node_start(config, "draft", "Taslak", "2. deneme", meta={"attempt": 2})

    event = queue.get_nowait()
    assert event["meta"] == {"attempt": 2}


@pytest.mark.asyncio
async def test_node_error_defaults_to_fatal_but_can_degrade():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_node_error(config, "judge", "Yargıç", "Zaman aşımı.", fatal=False, detail="timeout")

    event = queue.get_nowait()
    assert event["fatal"] is False
    assert event["detail"] == "timeout"


@pytest.mark.asyncio
async def test_node_skipped_carries_a_reason():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_node_skipped(config, "routing", "Yönlendirme", "Taslak adımı başarısız oldu.")

    event = queue.get_nowait()
    assert event["event"] == "node_skipped"
    assert event["reason"] == "Taslak adımı başarısız oldu."


@pytest.mark.asyncio
async def test_emit_interrupt_carries_kind_id_and_payload():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_interrupt(
        config, kind="missing_information", interrupt_id="abc123",
        payload={"questions": [{"key": "muhatap"}]},
    )

    event = queue.get_nowait()
    assert event["kind"] == "missing_information"
    assert event["interrupt_id"] == "abc123"
    assert event["payload"] == {"questions": [{"key": "muhatap"}]}


@pytest.mark.asyncio
async def test_emit_guardrail_event_carries_stage_kind_decision_and_reasons():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_guardrail_event(
        config, stage="output", kind="leakage", decision="redacted",
        reasons=["Kaynak evrakta desteklenmeyen iddia."],
    )

    event = queue.get_nowait()
    assert event["event"] == "guardrail"
    assert event["stage"] == "output"
    assert event["kind"] == "leakage"
    assert event["decision"] == "redacted"
    assert event["reasons"] == ["Kaynak evrakta desteklenmeyen iddia."]


@pytest.mark.asyncio
async def test_emit_guardrail_event_defaults_reasons_to_an_empty_list():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_guardrail_event(config, stage="input", kind="pii", decision="flagged")

    assert queue.get_nowait()["reasons"] == []


@pytest.mark.asyncio
async def test_emit_guardrail_event_is_a_no_op_without_a_queue():
    await emit_guardrail_event(None, stage="input", kind="pii", decision="flagged")
    await emit_guardrail_event({}, stage="input", kind="pii", decision="flagged")


@pytest.mark.asyncio
async def test_token_and_partial_result_shapes():
    queue: asyncio.Queue = asyncio.Queue()
    config = _config(queue)

    await emit_token(config, "draft", "merhaba")
    await emit_partial(config, "classification", {"document_type": "official_letter"})

    token = queue.get_nowait()
    partial = queue.get_nowait()
    assert token == {"event": "token", "node": "draft", "text": "merhaba", "seq": 1}
    assert partial == {
        "event": "partial_result", "key": "classification",
        "value": {"document_type": "official_letter"}, "seq": 2,
    }


@pytest.mark.asyncio
async def test_seq_is_monotonic_per_queue_and_independent_across_queues():
    queue_a: asyncio.Queue = asyncio.Queue()
    queue_b: asyncio.Queue = asyncio.Queue()

    await emit_token(_config(queue_a), "draft", "a1")
    await emit_token(_config(queue_b), "draft", "b1")
    await emit_token(_config(queue_a), "draft", "a2")

    assert queue_a.get_nowait()["seq"] == 1
    assert queue_b.get_nowait()["seq"] == 1
    assert queue_a.get_nowait()["seq"] == 2


@pytest.mark.asyncio
async def test_emit_reply_stream_chunks_the_text_and_reassembles_exactly():
    queue: asyncio.Queue = asyncio.Queue()
    text = "Sayın Makam, " * 10 + "Arz ederim."

    await emit_reply_stream(queue, text, chunk_size=8, chunk_delay_seconds=0)

    chunks = []
    while not queue.empty():
        event = queue.get_nowait()
        assert event["event"] == "token"
        assert event["node"] == "reply"
        chunks.append(event["text"])

    assert "".join(chunks) == text
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_emit_reply_stream_paces_chunks_for_visible_sse_updates(monkeypatch):
    queue: asyncio.Queue = asyncio.Queue()
    delays = []

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr("app.ai.workflows.events.asyncio.sleep", record_delay)

    await emit_reply_stream(
        queue,
        "abcdefghijkl",
        chunk_size=5,
        chunk_delay_seconds=0.025,
    )

    assert delays == [0.025, 0.025]
    assert [queue.get_nowait()["text"] for _ in range(3)] == ["abcde", "fghij", "kl"]


@pytest.mark.asyncio
async def test_emit_reply_stream_is_a_no_op_for_empty_text_or_no_queue():
    queue: asyncio.Queue = asyncio.Queue()
    await emit_reply_stream(queue, "")
    assert queue.empty()
    await emit_reply_stream(None, "merhaba")  # must not raise


def test_child_config_returns_empty_dict_for_no_parent_config():
    assert child_config(None) == {}
    assert child_config({}) == {}


def test_child_config_carries_configurable_and_callbacks_into_sub_graphs():
    """Sub-graph invocations must forward the parent config -- when they did
    not, the queue never reached the writer/editor nodes and the UI showed no
    progress during the longest phase of the pipeline."""
    queue: asyncio.Queue = asyncio.Queue()
    parent = {
        "configurable": {"status_queue": queue, "thread_id": "t1"},
        "callbacks": ["tracer"],
    }

    child = child_config(parent)

    assert child["configurable"]["status_queue"] is queue
    assert child["configurable"]["thread_id"] == "t1"
    assert child["callbacks"] == ["tracer"]


def test_child_config_copies_configurable_rather_than_aliasing_it():
    parent = {"configurable": {"thread_id": "t1"}}
    child = child_config(parent)
    child["configurable"]["thread_id"] = "mutated"

    assert parent["configurable"]["thread_id"] == "t1"
