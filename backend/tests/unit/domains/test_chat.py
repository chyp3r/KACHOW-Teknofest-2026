import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
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


class _FakeSessionContext:
    """Stands in for `AsyncSessionLocal()`'s async context manager, handing
    back a pre-configured mock session instead of a real DB connection."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def mock_db_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def chat_service_with_db(mock_planning_graph, mock_db_session):
    """A ChatService whose session_factory hands back `mock_db_session`
    instead of opening a real connection -- see ChatService's own docstring
    for why this can't just be a request-scoped Depends(get_db)."""
    return ChatService(
        planning_graph=mock_planning_graph,
        session_factory=lambda: _FakeSessionContext(mock_db_session),
    )


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


# --- Draft persistence (session_factory-based, see chat_service_with_db) -----


def _existing_draft(**overrides):
    from app.domains.drafts.model.draft_model import DraftModel

    defaults = dict(
        id="draft-1",
        user_id=None,
        session_id="s1",
        document_id=None,
        version=1,
        parent_draft_id=None,
        content="Önceki taslak.",
        correspondence_type=None,
        routed_unit=None,
        status="COMPLETED",
        confidence_score=90.0,
        instructions=None,
        is_deleted=False,
    )
    defaults.update(overrides)
    return DraftModel(**defaults)


@pytest.mark.asyncio
async def test_handle_message_fetches_the_last_draft_before_invoking_the_graph(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = _existing_draft()
    mock_db_session.execute.return_value = fetch_result

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {"status": "COMPLETED", "assist": {"reply": "Tamam."}}
    }

    request = ChatMessageRequest(message="Son taslağı kısalt.", session_id="s1")
    await chat_service_with_db.handle_message(request)

    graph_input = mock_planning_graph.ainvoke.call_args.args[0]
    assert graph_input["last_draft"]["content"] == "Önceki taslak."


@pytest.mark.asyncio
async def test_a_conversation_with_no_prior_draft_gets_an_empty_last_draft(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = fetch_result

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {"status": "COMPLETED", "assist": {"reply": "Merhaba."}}
    }

    request = ChatMessageRequest(message="Merhaba", session_id="s0")
    await chat_service_with_db.handle_message(request)

    graph_input = mock_planning_graph.ainvoke.call_args.args[0]
    assert graph_input["last_draft"] == {}


@pytest.mark.asyncio
async def test_handle_message_persists_a_new_draft_version_when_one_is_produced(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    no_prior = MagicMock()
    no_prior.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = no_prior

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {
                "draft": "Yeni taslak metni.",
                "status": "COMPLETED",
                "confidence_score": 88.0,
            },
            "routing": {"routed_unit": "Hukuk Müşavirliği"},
        }
    }

    request = ChatMessageRequest(
        message="Bu evraka cevap yazısı hazırla.", session_id="s2", document_id="uploads/x.pdf"
    )
    await chat_service_with_db.handle_message(request, user_id="user-1")

    assert mock_db_session.add.called
    mock_db_session.commit.assert_called_once()
    added_draft = mock_db_session.add.call_args.args[0]
    assert added_draft.content == "Yeni taslak metni."
    assert added_draft.user_id == "user-1"
    assert added_draft.document_id == "uploads/x.pdf"
    assert added_draft.routed_unit == "Hukuk Müşavirliği"
    assert added_draft.version == 1


@pytest.mark.asyncio
async def test_handle_message_does_not_duplicate_a_version_when_content_is_unchanged(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    """A plain approval on the human-in-the-loop gate produces the same draft
    text that was already stored -- must not mint a redundant version."""
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = _existing_draft(
        session_id="s3", content="Aynı taslak."
    )
    mock_db_session.execute.return_value = fetch_result

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Aynı taslak.", "status": "APPROVED"},
        }
    }

    request = ChatMessageRequest(message="Onaylıyorum", session_id="s3")
    await chat_service_with_db.handle_message(request)

    mock_db_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_a_revised_draft_chains_to_its_parent_version(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    fetch_result = MagicMock()
    fetch_result.scalar_one_or_none.return_value = _existing_draft(
        id="draft-1", session_id="s4", version=2, content="Eski hâl."
    )
    mock_db_session.execute.return_value = fetch_result

    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Revize edilmiş hâl.", "status": "COMPLETED"},
        }
    }

    request = ChatMessageRequest(message="Son taslağı kısalt.", session_id="s4")
    await chat_service_with_db.handle_message(request)

    added_draft = mock_db_session.add.call_args.args[0]
    assert added_draft.version == 3
    assert added_draft.parent_draft_id == "draft-1"


@pytest.mark.asyncio
async def test_a_db_failure_while_persisting_a_draft_does_not_fail_the_turn(
    chat_service_with_db, mock_planning_graph, mock_db_session
):
    mock_db_session.execute.side_effect = RuntimeError("db unavailable")
    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Taslak.", "status": "COMPLETED"},
        }
    }
    request = ChatMessageRequest(message="Taslak hazırla", session_id="s5")

    response = await chat_service_with_db.handle_message(request)

    assert response.workflow_status == "COMPLETED"
