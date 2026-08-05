import json
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.dependency import get_chat_service, get_document_repository, require_auth_if_enabled
from app.api.exceptions.authorization import AuthorizationException
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership, clearance_for
from app.domains.chat.chat_service import ChatService
from app.domains.chat.schema.chat_schema import ChatMessageRequest, ChatResumeRequest
from app.domains.documents.repository import DocumentRepository
from app.domains.users.model.user_model import UserModel

logger = logging.getLogger(__name__)


async def _verify_document_access(
    document_id: Optional[str],
    current_user: Optional[UserModel],
    document_repository: DocumentRepository,
) -> None:
    """Refuse a chat turn that attaches a document the caller doesn't own or
    isn't cleared for.

    A document being attached only changes which tools the assistant can
    call (see app.ai.tools.document_tools's module docstring) -- nothing
    upstream of that previously checked whether the caller was allowed to
    attach it in the first place. ``current_user=None`` (``REQUIRE_AUTH``
    disabled) skips both checks entirely, matching the open demo/dev path.
    ADMIN/MANAGER skip only the ownership half (see ``bypasses_ownership``)
    -- they see every document company-wide, but clearance still applies
    (though it never actually binds for them: see ``clearance_for``).

    This is the coarse, turn-level gate (may this caller even attach this
    document at all); ``document_tools.py``'s own deny-at-retrieval check is
    the finer-grained one underneath it, since a single turn's tools can
    also touch legislation search and other content this gate never sees.

    Raises:
        AuthorizationException: If the document is registered to a
            different owner than ``current_user`` (and it isn't an
            ADMIN/MANAGER), or ``current_user``'s clearance doesn't cover
            the document's confidentiality level.
    """
    if not document_id or current_user is None:
        return
    document = await document_repository.get_by_id(document_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    if document.owner_id != current_user.id and not bypasses_ownership(current_user):
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    try:
        document_level = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_level = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_level)

# See require_auth_if_enabled / settings.REQUIRE_AUTH: a no-op by default so
# the demo works without the frontend implementing a login flow.
router = APIRouter(
    prefix="/chat", tags=["chat"], dependencies=[Depends(require_auth_if_enabled)]
)


def make_serializable(obj: Any) -> Any:
    """Recursively convert workflow output into JSON-serializable values.

    Workflow state carries LangChain ``Document`` objects and Pydantic models
    that ``json.dumps`` cannot encode, and a single unencodable value anywhere in
    the tree would abort the whole SSE stream.

    Args:
        obj: Any value from the workflow state.

    Returns:
        An equivalent structure of JSON-safe primitives.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): make_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_serializable(item) for item in obj]
    if hasattr(obj, "page_content") and hasattr(obj, "metadata"):
        return {
            "page_content": obj.page_content,
            "metadata": make_serializable(obj.metadata),
        }
    if hasattr(obj, "model_dump"):
        try:
            return make_serializable(obj.model_dump(mode="json"))
        except Exception:
            return make_serializable(obj.model_dump())
    return str(obj)


def _sse_response(
    events: AsyncIterator[dict[str, Any]], http_request: Request
) -> StreamingResponse:
    """Wrap a workflow event stream in the shared SSE transport.

    Shared by ``/stream`` and ``/resume`` since a resumed run streams exactly
    the same event vocabulary as a fresh one.

    Args:
        events: The service's async event generator.
        http_request: The inbound request, polled for client disconnects.

    Returns:
        A ``text/event-stream`` response.
    """

    async def event_generator():
        try:
            async for event in events:
                # Stop the workflow as soon as the client goes away instead of
                # holding the local model busy for a response nobody will read.
                if await http_request.is_disconnected():
                    logger.info("Client disconnected; aborting chat stream.")
                    break
                payload = json.dumps(make_serializable(event), ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("Chat stream failed")
            error = json.dumps(
                {"event": "error", "message": "Akış sırasında bir hata oluştu."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx buffers proxied responses by default, which would defeat the
            # entire point of streaming.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/message", response_model=None)
async def send_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """Orchestrate a chat interaction and return the completed result.

    Routes the user input through the master planning graph, which resolves
    whether it needs analysis, drafting, document Q&A or plain conversation.
    May also return an ``INTERRUPTED`` status when the run paused at the
    human-in-the-loop gate; resume it via ``POST /chat/resume``.
    """
    await _verify_document_access(request.document_id, current_user, document_repository)
    clearance = clearance_for(current_user)
    result = await service.handle_message(
        request,
        user_id=current_user.id if current_user else None,
        requester_clearance=clearance.value if clearance else None,
    )
    return SuccessResponse(data=make_serializable(result.model_dump()))


@router.post("/stream")
async def stream_chat_message(
    request: ChatMessageRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=20, window_seconds=60, key_prefix="chat:stream")),
):
    """Orchestrate a chat interaction and stream progress events over SSE.

    Emits ``session`` first with the resolved thread_id, then
    ``node_start``/``node_end``/``node_skipped``/``node_error`` for workflow
    phases, ``token`` for live text as it is generated, ``partial_result`` for
    intermediate output the client can render before the run finishes, and
    either a terminal ``final_result`` or, if the run paused at the
    human-in-the-loop gate, an ``interrupt`` event carrying what the human
    needs to answer.
    """
    # Checked before entering the SSE response, not inside the generator, so
    # a denied request gets a normal 403 instead of a stream that opens and
    # then immediately reports a generic error.
    await _verify_document_access(request.document_id, current_user, document_repository)
    user_id = current_user.id if current_user else None
    clearance = clearance_for(current_user)
    return _sse_response(
        service.handle_message_stream(
            request, user_id=user_id, requester_clearance=clearance.value if clearance else None
        ),
        http_request,
    )


@router.post("/resume", response_model=None)
async def resume_chat_stream(
    request: ChatResumeRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=30, window_seconds=60, key_prefix="chat:resume")),
):
    """Resume a run paused at the human-in-the-loop gate, streaming over SSE.

    ``action="answer"`` fills in a draft's missing-information placeholders
    without regenerating it. ``action="approve"|"revise"|"reject"`` resolves a
    draft that needed a human's sign-off before unit routing.
    """
    user_id = current_user.id if current_user else None
    ChatService._verify_thread_ownership(request.session_id, user_id)
    return _sse_response(
        service.resume_stream(request.session_id, request, user_id=user_id), http_request
    )


@router.post("/resume/sync", response_model=None)
async def resume_chat_sync(
    request: ChatResumeRequest,
    service: ChatService = Depends(get_chat_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """Resume a paused run and return the completed (or re-paused) result."""
    result = await service.resume(
        request.session_id, request, user_id=current_user.id if current_user else None
    )
    return SuccessResponse(data=make_serializable(result.model_dump()))


@router.get("/sessions/{session_id}/state", response_model=None)
async def get_session_state(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
    current_user: Optional[UserModel] = Depends(require_auth_if_enabled),
):
    """Report whether a session is idle, running, or paused on an interrupt.

    Lets the client recover after a page reload or a dropped SSE connection:
    if ``status`` is ``"interrupted"``, re-render the resume form from the
    returned ``interrupt`` payload instead of losing it.
    """
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required.")
    state = await service.get_session_state(
        session_id, user_id=current_user.id if current_user else None
    )
    return SuccessResponse(data=state)
