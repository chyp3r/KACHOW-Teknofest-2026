"""Tests for the new-message notification listener in app.events.subscribers.

Same mocked-session pattern as test_draft_share_subscribers.py.
"""

from unittest.mock import AsyncMock

import pytest

from app.events import subscribers
from app.events.event import ConversationMessageCreatedEvent


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def fake_service(monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr(subscribers, "tenant_session", lambda company_id=None, is_root=False: _FakeSessionContext(object()))
    monkeypatch.setattr(subscribers, "NotificationRepository", lambda session: object())
    monkeypatch.setattr(subscribers, "NotificationService", lambda repository, cache=None: service)
    monkeypatch.setattr(subscribers, "get_cache", lambda: object())
    return service


async def test_new_message_notifies_the_recipient(fake_service):
    event = ConversationMessageCreatedEvent(
        payload={
            "company_id": "company-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "sender_id": "emp-1",
            "sender_username": "aylin",
            "recipient_id": "emp-2",
            "kind": "text",
            "body_preview": "merhaba, müsait misin?",
        }
    )

    await subscribers._notify_new_message(event)

    fake_service.create.assert_awaited_once()
    kwargs = fake_service.create.await_args.kwargs
    assert kwargs["company_id"] == "company-1"
    assert kwargs["user_id"] == "emp-2"
    assert kwargs["type"] == "conversation_message"
    assert "aylin" in kwargs["title"]
    assert kwargs["body"] == "merhaba, müsait misin?"
    assert kwargs["resource_type"] == "conversation"
    assert kwargs["resource_id"] == "conv-1"


async def test_new_message_never_leaks_full_body_beyond_the_preview(fake_service):
    """The notification body is exactly `body_preview` -- the subscriber has
    no access to the full message and must never widen it."""
    event = ConversationMessageCreatedEvent(
        payload={
            "company_id": "company-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
            "sender_id": "emp-1",
            "sender_username": "aylin",
            "recipient_id": "emp-2",
            "kind": "text",
            "body_preview": "kısa özet",
        }
    )

    await subscribers._notify_new_message(event)

    kwargs = fake_service.create.await_args.kwargs
    assert kwargs["body"] == "kısa özet"
