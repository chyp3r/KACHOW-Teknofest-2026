import asyncio

import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock

from app.api.exceptions.ai_error import AIException
from app.core.enums.reasoning_level import ReasoningLevel
from app.domains.chat.chat_service import ChatService
from app.domains.chat.schema.chat_schema import ChatMessageRequest


@pytest.fixture
def mock_planning_graph():
    graph = AsyncMock()
    # A state snapshot with an empty `.next` means the run completed rather
    # than pausing at the human_gate node -- without this, _is_paused() reads
    # a MagicMock's auto-created `.next` attribute, which is truthy, and every
    # response below would be misread as an interrupt.
    graph.aget_state.return_value = MagicMock(next=())
    return graph


@pytest.fixture
def chat_service(mock_planning_graph):
    return ChatService(planning_graph=mock_planning_graph)


@pytest.mark.asyncio
async def test_chat_service_plain_chat(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Merhaba", session_id="123")

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "assist": {"reply": "Merhaba, size nasıl yardımcı olabilirim?"}
        }
    }

    response = await chat_service.handle_message(request)

    assert response.workflow_status == "COMPLETED"
    assert response.reply == "Merhaba, size nasıl yardımcı olabilirim?"
    assert response.session_id == "123"
    mock_planning_graph.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_end_orphaned_run_closes_out_the_run_row(chat_service, mock_planning_graph, monkeypatch):
    """A timed-out or crashed turn never reaches consolidate_memory_node --
    the only place end_run() is normally called -- so the runs row
    planning_node's own start_run wrote would stay "running" forever
    without this."""
    from app.domains.chat import chat_service as chat_service_module

    end_run = AsyncMock()
    monkeypatch.setattr(chat_service_module, "end_run", end_run)
    mock_planning_graph.aget_state.return_value = MagicMock(
        values={"run_id": "run-1", "company_id": "company-1"}
    )

    await chat_service._end_orphaned_run({}, "timeout")

    end_run.assert_called_once_with(run_id="run-1", status="timeout", company_id="company-1")


@pytest.mark.asyncio
async def test_end_orphaned_run_is_a_silent_no_op_without_a_recoverable_run_id(
    chat_service, mock_planning_graph, monkeypatch
):
    """No checkpointer (aget_state raises), or a snapshot with no run_id at
    all (nothing ever got as far as planning_node) -- both must degrade
    silently, never raise a second exception on top of the one the caller
    is already handling."""
    from app.domains.chat import chat_service as chat_service_module

    end_run = AsyncMock()
    monkeypatch.setattr(chat_service_module, "end_run", end_run)
    mock_planning_graph.aget_state.side_effect = RuntimeError("no checkpointer configured")

    await chat_service._end_orphaned_run({}, "timeout")

    end_run.assert_not_called()


@pytest.mark.asyncio
async def test_chat_service_document_qa(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Bu belgede ne diyor?")

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "assist": {"reply": "Belge kuralları anlatıyor."}
        }
    }

    response = await chat_service.handle_message(request)

    assert response.workflow_status == "COMPLETED"
    assert response.reply == "Belge kuralları anlatıyor."


@pytest.mark.asyncio
async def test_chat_service_draft(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Bana taslak yaz")

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Bu bir resmi taslaktır."}
        }
    }

    response = await chat_service.handle_message(request)

    assert response.workflow_status == "COMPLETED"
    assert "Bu bir resmi taslaktır." in response.reply


@pytest.mark.asyncio
async def test_chat_service_draft_response_carries_the_persisted_draft_id(
    chat_service, mock_planning_graph, monkeypatch
):
    """The bug this closes: the chat response's own `details.draft` never
    carried the persisted `drafts.id` back to the frontend, so nothing in
    the chat UI (the "Birimi değiştir" picker, in particular) could address
    the exact draft this turn just produced -- see ChatService.
    _maybe_record_draft's own docstring on why this has to be injected
    before the response is built, not after.

    `draft_recorder.record_draft` itself (the real DB write) has its own
    coverage elsewhere -- mocked here so this test is purely about the
    wiring: the id a write returns must reach `response.details["draft"]
    ["id"]`.
    """
    from app.domains.chat import chat_service as chat_service_module

    monkeypatch.setattr(
        chat_service_module.draft_recorder,
        "record_draft",
        AsyncMock(return_value="draft-abc-123"),
    )
    request = ChatMessageRequest(message="Bana taslak yaz")

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Bu bir resmi taslaktır."},
        }
    }

    response = await chat_service.handle_message(request)

    draft_details = response.details.get("draft") or {}
    assert draft_details.get("id") == "draft-abc-123"


@pytest.mark.asyncio
async def test_the_streamed_final_result_event_also_carries_the_draft_id(
    chat_service, mock_planning_graph, monkeypatch
):
    """Same bug, the other call site: `_enqueue_terminal_event` used to push
    `final_result` onto the SSE queue *before* recording the draft, so this
    (the path the actual chat UI streams from) could never carry the id
    either -- by the time recording finished, the client already had the
    response. Recording now happens first."""
    import asyncio

    from app.domains.chat import chat_service as chat_service_module

    monkeypatch.setattr(
        chat_service_module.draft_recorder,
        "record_draft",
        AsyncMock(return_value="draft-xyz-789"),
    )
    queue: asyncio.Queue = asyncio.Queue()
    state = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Bu bir resmi taslaktır."},
        }
    }
    config = {"configurable": {}}

    await chat_service._enqueue_terminal_event(queue, state, config, "thread-1")

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    final_result = next(event for event in events if event.get("event") == "final_result")
    assert final_result["details"]["draft"]["id"] == "draft-xyz-789"


@pytest.mark.asyncio
async def test_chat_service_reports_interrupt_without_a_checkpointer_configured(
    chat_service, mock_planning_graph
):
    """No checkpointer means aget_state() raises; that must read as 'not
    paused', not bubble up and fail the whole request."""
    mock_planning_graph.aget_state.side_effect = Exception("no checkpointer configured")
    mock_planning_graph.ainvoke.return_value = {
        "final_output": {"status": "COMPLETED", "assist": {"reply": "Tamamdır."}}
    }
    request = ChatMessageRequest(message="Selam")

    response = await chat_service.handle_message(request)

    assert response.workflow_status == "COMPLETED"
    assert response.reply == "Tamamdır."


@pytest.mark.asyncio
async def test_chat_service_reports_paused_run_as_interrupted(chat_service, mock_planning_graph):
    """The pre-invoke guard sees an untouched (not-yet-paused) thread and lets
    the call through; the graph itself pauses during ainvoke(), which the
    post-invoke check must then report as INTERRUPTED rather than COMPLETED.

    Three aget_state() calls total: the pre-invoke guard in _invoke(), then
    _response_from_state()'s own _is_paused() check, then a second direct
    fetch there to extract the interrupt payload.
    """
    paused_snapshot = MagicMock(next=("human_gate",), tasks=())
    mock_planning_graph.aget_state.side_effect = [
        MagicMock(next=()),
        paused_snapshot,
        paused_snapshot,
    ]

    request = ChatMessageRequest(message="Devam et")
    response = await chat_service.handle_message(request)

    assert response.workflow_status == "INTERRUPTED"


@pytest.mark.asyncio
async def test_chat_service_rejects_new_message_on_already_paused_session(
    chat_service, mock_planning_graph
):
    """Starting a fresh run on a thread with an outstanding interrupt is not a
    supported resume path -- the caller must use /chat/resume instead."""
    mock_planning_graph.aget_state.return_value = MagicMock(next=("human_gate",), tasks=())

    request = ChatMessageRequest(message="Devam et", session_id="paused-session")

    with pytest.raises(AIException):
        await chat_service.handle_message(request)
    mock_planning_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_concurrent_messages_on_the_same_session_are_serialized(chat_service, mock_planning_graph):
    """C13/C14: a double submission on the same session (a fast
    double-click, a client retry racing the first request) must not race
    two concurrent ainvoke() calls against the same checkpoint -- the
    second call's own turn only starts once the first has fully settled,
    not somewhere in the middle of it."""
    order: list[str] = []

    async def _slow_ainvoke(_graph_input, config):
        thread_id = config["configurable"]["thread_id"]
        order.append(f"start-{thread_id}")
        await asyncio.sleep(0.02)
        order.append(f"end-{thread_id}")
        return {"final_output": {"status": "COMPLETED", "assist": {"reply": "ok"}}}

    mock_planning_graph.ainvoke = _slow_ainvoke
    request = ChatMessageRequest(message="Merhaba", session_id="concurrent-session")

    await asyncio.gather(
        chat_service.handle_message(request), chat_service.handle_message(request)
    )

    # Each turn's own start/end pair completes before the next turn's start
    # -- never two "start"s back to back, which is what an unserialized
    # race would produce.
    assert order == [
        "start-concurrent-session", "end-concurrent-session",
        "start-concurrent-session", "end-concurrent-session",
    ]


def test_chat_message_request_defaults_reasoning_level_to_balanced():
    """The zero-regression contract: an older caller that never sends this
    field must resolve to today's pre-existing behaviour."""
    request = ChatMessageRequest(message="Merhaba")

    assert request.reasoning_level == ReasoningLevel.BALANCED


def test_chat_message_request_rejects_an_invalid_reasoning_level():
    with pytest.raises(ValidationError):
        ChatMessageRequest(message="Merhaba", reasoning_level="ultra")


@pytest.mark.asyncio
async def test_chat_service_threads_the_requested_reasoning_level_into_the_graph(
    chat_service, mock_planning_graph
):
    request = ChatMessageRequest(message="Bana hızlı bir taslak yaz", reasoning_level="fast")

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {"status": "COMPLETED", "assist": {"reply": "Tamam."}}
    }

    await chat_service.handle_message(request)

    graph_input = mock_planning_graph.ainvoke.call_args.args[0]
    assert graph_input["reasoning_level"] == "fast"


# ==========================================
# Ownership (Faz 5): thread_id <-> user_id
# ==========================================
def test_thread_id_is_unchanged_for_an_anonymous_caller():
    """The REQUIRE_AUTH=False demo/dev path keeps today's behaviour exactly."""
    assert ChatService._thread_id("abc", user_id=None) == "abc"


def test_thread_id_embeds_the_authenticated_user():
    assert ChatService._thread_id("abc", user_id="user-1") == "user-1:abc"


def test_thread_id_generates_a_session_id_when_authenticated_and_none_given():
    thread_id = ChatService._thread_id(None, user_id="user-1")
    assert thread_id.startswith("user-1:")


def test_owns_thread_is_always_true_when_unauthenticated():
    assert ChatService._owns_thread("user-2:some-session", user_id=None) is True


def test_owns_thread_true_for_the_thread_s_own_user():
    assert ChatService._owns_thread("user-1:abc", user_id="user-1") is True


def test_owns_thread_false_for_a_different_user():
    """The core IDOR check: user B must not be able to resume/inspect a
    thread that was created under user A's id."""
    assert ChatService._owns_thread("user-1:abc", user_id="user-2") is False


@pytest.mark.asyncio
async def test_resume_refuses_a_thread_belonging_to_a_different_user(
    chat_service, mock_planning_graph
):
    from app.api.exceptions.authorization import AuthorizationException
    from app.domains.chat.schema.chat_schema import ChatResumeRequest

    request = ChatResumeRequest(session_id="user-1:abc", action="approve")

    with pytest.raises(AuthorizationException):
        await chat_service.resume("user-1:abc", request, user_id="user-2")

    mock_planning_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_resume_records_the_turn_with_the_documents_own_id_not_none(
    chat_service, mock_planning_graph, monkeypatch
):
    """C14: PlanningState.document_id survives a checkpointer resume
    unchanged, but resume()/resume_stream() used to hardcode document_id=None
    when recording the turn regardless -- every draft settled through a
    gate (missing-information, brief, approval) lost its attachment even
    though the original turn had a document."""
    from app.domains.chat import chat_service as chat_service_module
    from app.domains.chat.schema.chat_schema import ChatResumeRequest

    record_turn = AsyncMock()
    monkeypatch.setattr(chat_service_module.chat_recorder, "record_turn", record_turn)

    mock_planning_graph.ainvoke.return_value = {
        "document_id": "doc-42",
        "final_output": {"status": "COMPLETED", "assist": {"reply": "Tamam."}},
    }
    request = ChatResumeRequest(session_id="thread-1", action="approve")

    await chat_service.resume("thread-1", request)

    assert record_turn.call_args.kwargs["document_id"] == "doc-42"


@pytest.mark.asyncio
async def test_get_session_state_refuses_a_thread_belonging_to_a_different_user(
    chat_service,
):
    from app.api.exceptions.authorization import AuthorizationException

    with pytest.raises(AuthorizationException):
        await chat_service.get_session_state("user-1:abc", user_id="user-2")


# ==========================================
# Revision pipeline: reject reason, conflicts, changelog surfaced to the user
# ==========================================
def test_resume_payload_carries_the_reject_reason():
    from app.domains.chat.schema.chat_schema import ChatResumeRequest

    request = ChatResumeRequest(
        session_id="s", action="reject", reason="Üslup çok resmi değil."
    )

    payload = ChatService._resume_payload(request)

    assert payload["reason"] == "Üslup çok resmi değil."


def test_resume_summary_renders_the_reject_reason():
    from app.domains.chat.schema.chat_schema import ChatResumeRequest

    request = ChatResumeRequest(
        session_id="s", action="reject", reason="Üslup çok resmi değil."
    )

    assert ChatService._resume_summary(request) == "reject: Üslup çok resmi değil."


def test_select_reply_omits_the_rejection_reason_now_carried_as_structured_details():
    """Rejection reason, approval notes, routing unit and the changelog
    summary all used to be appended to the reply as free text; they are now
    structured data the frontend reads off the same final_output (as
    ``details`` on the chat message) and renders as its own meta strip (see
    DraftMetaStrip) -- the reply itself is the draft text alone."""
    final_output = {
        "draft": {
            "draft": "Taslak metni",
            "status": "REJECTED",
            "rejection_reason": "Üslup çok resmi değil.",
        }
    }

    reply = ChatService._select_reply(final_output)

    assert reply == "Resmî yazı taslağınız hazırlandı.\n\nTaslak metni"
    assert final_output["draft"]["rejection_reason"] == "Üslup çok resmi değil."


def test_select_reply_omits_conflicts_now_delivered_as_a_separate_live_notice():
    """A conflict finding is no longer folded into the merged reply text --
    app.ai.workflows.revise_graph.audit_node now publishes it live as its own
    "notice" SSE event instead (rendered as a separate chat message, never a
    blocking popup). The structured finding itself is untouched, still
    reachable via final_output["draft"]["conflicts"] for any caller that
    wants it programmatically (e.g. the non-streaming REST path, which has
    no notice channel) -- only the free-text reply omits it, to avoid
    showing the same warning twice on the streaming path."""
    final_output = {
        "draft": {
            "draft": "Taslak metni",
            "status": "NEEDS_HUMAN_APPROVAL",
            "requires_human_approval": True,
            "evaluation_notes": "not",
            "conflicts": [
                {
                    "kind": "mevzuat_dayanaksiz",
                    "severity": "major",
                    "detail": "4982 sayılı atıf mevzuat bağlamında yok.",
                }
            ],
        }
    }

    reply = ChatService._select_reply(final_output)

    assert "4982 sayılı atıf mevzuat bağlamında yok." not in reply
    assert final_output["draft"]["conflicts"][0]["detail"] == (
        "4982 sayılı atıf mevzuat bağlamında yok."
    )


def test_select_reply_omits_the_changelog_summary_now_carried_as_structured_details():
    final_output = {
        "draft": {
            "draft": "Taslak metni",
            "status": "COMPLETED",
            "changelog": {"summary": "1 bölüm değiştirildi."},
        }
    }

    reply = ChatService._select_reply(final_output)

    assert "1 bölüm değiştirildi." not in reply
    assert final_output["draft"]["changelog"]["summary"] == "1 bölüm değiştirildi."
