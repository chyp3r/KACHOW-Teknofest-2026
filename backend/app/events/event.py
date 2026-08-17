from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    """SOTA base event structure for loose coupling between domains."""
    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique ID of the event")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Time of the event")
    event_type: str = Field(description="Name/type of the event")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event data payload")

class DocumentUploadedEvent(BaseEvent):
    event_type: str = "document.uploaded"

class DocumentClassifiedEvent(BaseEvent):
    event_type: str = "document.classified"

class DocumentAnalyzedEvent(BaseEvent):
    event_type: str = "document.analyzed"

class DraftCreatedEvent(BaseEvent):
    event_type: str = "draft.created"

class DraftSharedEvent(BaseEvent):
    """One `draft_shares` row created (`POST /drafts/{id}/send`).

    Published once per recipient, not once per bulk send call -- see
    `DraftShareService.send`'s docstring for why. `payload` carries
    `company_id`, `share_id`, `draft_id`, `sender_id`, `sender_username`,
    `recipient_id`; the subscriber in `app.events.subscribers` turns this
    into one `notifications` row plus a live SSE push for `recipient_id`.
    """
    event_type: str = "draft.shared"

class DraftShareRespondedEvent(BaseEvent):
    """A recipient accepted or rejected a shared draft (never published for
    "read" or "withdrawn" -- see `DraftShareService`'s own docstring for
    why those two don't notify). `payload` carries `company_id`,
    `share_id`, `draft_id`, `sender_id`, `recipient_id`,
    `recipient_username`, `status` ("accepted"|"rejected"), `response_note`.
    """
    event_type: str = "draft.share_responded"

class DocumentRoutedEvent(BaseEvent):
    event_type: str = "document.routed"

class ArtifactTransferredEvent(BaseEvent):
    """One `artifact_transfers` row created (`ArtifactTransferService.
    execute`, any channel). `payload` carries `company_id`, `transfer_id`,
    `artifact_kind` ("draft"|"document"), `sender_id`, `sender_username`,
    `recipient_id`, `conversation_id` -- the subscriber in
    `app.events.subscribers` turns this into one `notifications` row for
    `recipient_id`. Deliberately no `body_preview`/content field: unlike a
    plain chat message, an artifact transfer's own `conversation_messages`
    row (`kind="artifact"`) already carries everything the recipient needs
    to see, and the notification only has to point at it -- see
    `ConversationMessageCreatedEvent`'s own docstring for why a durable,
    broadly-read record should never carry content that belongs only in
    the participation-gated thread.
    """
    event_type: str = "artifact.transferred"

class ConversationMessageCreatedEvent(BaseEvent):
    """One `conversation_messages` row created for one active recipient.

    Published once per active (non-left) recipient other than the sender,
    same convention `DraftSharedEvent` already uses for a multi-recipient
    fan-out (see `app.domains.drafts.draft_share_service.DraftShareService.
    send`'s docstring) -- a group message with N members publishes N of
    these, not one event carrying a recipient list. `payload` carries
    `company_id`, `conversation_id`, `message_id`, `sender_id`,
    `sender_username`, `recipient_id`, `kind` ("text"|"artifact"),
    `body_preview` (truncated -- never the full message body, see the
    subscriber's own docstring for why).
    """
    event_type: str = "messaging.message_created"

class UserCreatedEvent(BaseEvent):
    event_type: str = "user.created"

class UserDeletedEvent(BaseEvent):
    event_type: str = "user.deleted"

class UserPasswordChangedEvent(BaseEvent):
    event_type: str = "user.password_changed"
