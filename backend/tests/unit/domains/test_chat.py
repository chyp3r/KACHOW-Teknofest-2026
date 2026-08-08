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


def test_select_reply_includes_the_rejection_reason():
    final_output = {
        "draft": {
            "draft": "Taslak metni",
            "status": "REJECTED",
            "rejection_reason": "Üslup çok resmi değil.",
        }
    }

    reply = ChatService._select_reply(final_output)

    assert "reddedildi" in reply
    assert "Üslup çok resmi değil." in reply


def test_select_reply_surfaces_conflicts_without_implying_the_edit_was_reverted():
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

    assert "uygulandı" in reply
    assert "4982 sayılı atıf mevzuat bağlamında yok." in reply


def test_select_reply_includes_the_changelog_summary():
    final_output = {
        "draft": {
            "draft": "Taslak metni",
            "status": "COMPLETED",
            "changelog": {"summary": "1 bölüm değiştirildi."},
        }
    }

    reply = ChatService._select_reply(final_output)

    assert "1 bölüm değiştirildi." in reply
