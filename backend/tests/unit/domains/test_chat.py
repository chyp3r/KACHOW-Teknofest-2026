import pytest
from unittest.mock import AsyncMock, MagicMock

from app.api.exceptions.ai_error import AIException
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
            "chat": {"reply": "Merhaba, size nasıl yardımcı olabilirim?"}
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
            "document_qa": {"reply": "Belge kuralları anlatıyor."}
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
        "final_output": {"status": "COMPLETED", "chat": {"reply": "Tamamdır."}}
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
