import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependency import require_auth_if_enabled
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.domains.messaging.model.conversation_message_model import ConversationMessageModel
from app.domains.messaging.model.conversation_model import ConversationModel
from app.domains.messaging.model.conversation_participant_model import ConversationParticipantModel
from app.domains.messaging.repository import (
    ConversationMessageRepository,
    ConversationParticipantRepository,
    ConversationRepository,
)
from app.domains.messaging.schema.conversation_schema import (
    ConversationCreateRequest,
    ConversationResponse,
    ConversationUpdateRequest,
    ParticipantAddRequest,
    ParticipantResponse,
)
from app.domains.messaging.schema.message_schema import MarkReadRequest, MessageCreateRequest, MessageResponse
from app.domains.messaging.service import ConversationService, messaging_channel_for
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.cache import get_cache
from app.infrastructure.database.session import get_db
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

logger = logging.getLogger(__name__)

# Authentication is mandatory (see require_auth_if_enabled) -- every route in
# this router carries a real, tenant-bound current_user.
router = APIRouter(
    prefix="/messaging", tags=["messaging"], dependencies=[Depends(require_auth_if_enabled)]
)


def _service(db: AsyncSession) -> ConversationService:
    return ConversationService(
        conversation_repository=ConversationRepository(db),
        participant_repository=ConversationParticipantRepository(db),
        message_repository=ConversationMessageRepository(db),
        user_repository=UserRepository(db),
        cache=get_cache(),
    )


async def _participant_responses(
    db: AsyncSession, participants: List[ConversationParticipantModel]
) -> List[ParticipantResponse]:
    user_repository = UserRepository(db)
    responses = []
    for participant in participants:
        user = await user_repository.get_by_id(participant.user_id)
        responses.append(
            ParticipantResponse(
                user_id=participant.user_id,
                username=user.username if user else participant.user_id,
                role_in_conversation=participant.role_in_conversation,
                joined_at=participant.created_at,
                left_at=participant.left_at,
            )
        )
    return responses


async def _conversation_response(
    db: AsyncSession,
    conversation: ConversationModel,
    caller_participant: ConversationParticipantModel,
    all_participants: List[ConversationParticipantModel],
    message_repository: ConversationMessageRepository,
) -> ConversationResponse:
    unread = await message_repository.count_unread(
        conversation.id, conversation.company_id, caller_participant.last_read_message_id
    )
    return ConversationResponse(
        id=conversation.id,
        kind=conversation.kind,
        title=conversation.title,
        last_message_at=conversation.last_message_at,
        is_archived=conversation.is_archived,
        created_at=conversation.created_at,
        participants=await _participant_responses(db, all_participants),
        unread_count=unread,
        role_in_conversation=caller_participant.role_in_conversation,
    )


def _message_response(message: ConversationMessageModel, sender_username: Optional[str]) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
        sender_username=sender_username,
        kind=message.kind,
        body=message.body,
        artifact_transfer_id=message.artifact_transfer_id,
        created_at=message.created_at,
    )


@router.post("/conversations", response_model=None)
async def create_conversation(
    request: ConversationCreateRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Open a DM (idempotent) or create a group conversation."""
    service = _service(db)
    if request.kind == "dm":
        conversation = await service.open_dm(current_user.company_id, current_user, request.participant_id)
    else:
        conversation = await service.create_group(
            current_user.company_id, current_user, request.title, request.participant_ids
        )
    _, participant, all_participants = await service.get_conversation(
        conversation.id, current_user.company_id, current_user
    )
    response = await _conversation_response(
        db, conversation, participant, all_participants, ConversationMessageRepository(db)
    )
    return SuccessResponse(data=response.model_dump(mode="json"))


@router.get("/conversations", response_model=None)
async def list_conversations(
    pagination: PaginationParam = Depends(),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """The caller's active conversations, most recent activity first."""
    service = _service(db)
    items, total = await service.list_conversations(
        current_user.company_id, current_user, skip=pagination.offset, limit=pagination.limit
    )
    message_repository = ConversationMessageRepository(db)
    page_items = []
    for conversation, participant in items:
        all_participants = await service.list_participants(conversation.id, current_user.company_id)
        response = await _conversation_response(
            db, conversation, participant, all_participants, message_repository
        )
        page_items.append(response.model_dump(mode="json"))
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items, total=total, page=pagination.page, size=pagination.size, pages=pages
        ).model_dump()
    )


@router.get("/conversations/{conversation_id}", response_model=None)
async def get_conversation(
    conversation_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    service = _service(db)
    conversation, participant, all_participants = await service.get_conversation(
        conversation_id, current_user.company_id, current_user
    )
    response = await _conversation_response(
        db, conversation, participant, all_participants, ConversationMessageRepository(db)
    )
    return SuccessResponse(data=response.model_dump(mode="json"))


@router.patch("/conversations/{conversation_id}", response_model=None)
async def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Rename/archive a group conversation (owner, or Admin/Manager/Root)."""
    service = _service(db)
    conversation = await service.update_conversation(
        conversation_id, current_user.company_id, current_user, request.title, request.is_archived
    )
    _, participant, all_participants = await service.get_conversation(
        conversation_id, current_user.company_id, current_user
    )
    response = await _conversation_response(
        db, conversation, participant, all_participants, ConversationMessageRepository(db)
    )
    return SuccessResponse(data=response.model_dump(mode="json"))


@router.post("/conversations/{conversation_id}/participants", response_model=None)
async def add_participants(
    conversation_id: str,
    request: ParticipantAddRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Add members to a group conversation (owner, or Admin/Manager/Root)."""
    service = _service(db)
    added = await service.add_participants(
        conversation_id, current_user.company_id, current_user, request.user_ids
    )
    return SuccessResponse(data=await _participant_responses(db, added))


@router.delete("/conversations/{conversation_id}/participants/{user_id}", response_model=None)
async def remove_participant(
    conversation_id: str,
    user_id: str,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Leave a group (self) or remove another member (owner, or Admin/Manager/Root)."""
    service = _service(db)
    await service.remove_participant(conversation_id, current_user.company_id, current_user, user_id)
    return SuccessResponse(data={"removed": True})


@router.get("/conversations/{conversation_id}/messages", response_model=None)
async def list_messages(
    conversation_id: str,
    before_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """Keyset page of messages, newest first (`before_id` to page older)."""
    service = _service(db)
    messages = await service.list_messages(
        conversation_id, current_user.company_id, current_user, before_id=before_id, limit=limit
    )
    user_repository = UserRepository(db)
    items = []
    for message in messages:
        sender = await user_repository.get_by_id(message.sender_id) if message.sender_id else None
        items.append(_message_response(message, sender.username if sender else None).model_dump(mode="json"))
    return SuccessResponse(data=items)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=None,
    dependencies=[Depends(rate_limit(max_requests=30, window_seconds=60, key_prefix="messaging_send"))],
)
async def send_message(
    conversation_id: str,
    request: MessageCreateRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    service = _service(db)
    message = await service.send_text_message(
        conversation_id, current_user.company_id, current_user, request.body
    )
    return SuccessResponse(
        data=_message_response(message, current_user.username).model_dump(mode="json")
    )


@router.post("/conversations/{conversation_id}/read", response_model=None)
async def mark_read(
    conversation_id: str,
    request: MarkReadRequest,
    current_user: UserModel = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    service = _service(db)
    participant = await service.mark_read(
        conversation_id, current_user.company_id, current_user, request.message_id
    )
    return SuccessResponse(data={"last_read_message_id": participant.last_read_message_id})


#: Same disconnect-polling cadence as `notifications/router.py`'s own SSE
#: stream -- long enough to not busy-loop, short enough for a dropped
#: connection to be noticed promptly.
_POLL_TIMEOUT_SECONDS = 20.0


@router.get("/stream")
async def stream_messages(
    http_request: Request,
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Live-push new messages over SSE, one connection per user across every
    conversation they're in -- same Redis pub/sub pattern as
    `notifications/router.py::stream_notifications`, distinct channel
    prefix (see `messaging_channel_for`'s docstring). A dropped or never-
    received push is never data loss: `GET /messaging/conversations/{id}/
    messages` always has the row regardless of whether this stream was
    connected when it was sent.
    """
    cache = get_cache()
    await cache.connect()
    channel = messaging_channel_for(current_user.company_id, current_user.id)
    pubsub = cache.client.pubsub()
    await pubsub.subscribe(channel)

    async def event_generator():
        try:
            yield 'data: {"event": "connected"}\n\n'
            while True:
                if await http_request.is_disconnected():
                    logger.info("Client disconnected; closing messaging stream.")
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=_POLL_TIMEOUT_SECONDS
                )
                if message is None:
                    yield ": keep-alive\n\n"
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
        except Exception:
            logger.exception("Messaging stream failed")
            error = json.dumps(
                {"event": "error", "message": "Mesaj akışı sırasında bir hata oluştu."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n"
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
