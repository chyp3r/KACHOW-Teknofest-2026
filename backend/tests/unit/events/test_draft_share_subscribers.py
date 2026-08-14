"""Tests for the draft-share notification listeners in app.events.subscribers.

Same mocked-session pattern as test_guardrail_recorder.py/test_run_recorder.py:
`tenant_session` is monkeypatched to a fake async context manager so these
stay real unit tests, not integration tests against Postgres.
"""

from unittest.mock import AsyncMock

import pytest

from app.events import subscribers
from app.events.event import DraftSharedEvent, DraftShareRespondedEvent


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


async def test_draft_shared_notifies_the_recipient(fake_service):
    event = DraftSharedEvent(
        payload={
            "company_id": "company-1",
            "share_id": "share-1",
            "draft_id": "draft-1",
            "sender_id": "emp-1",
            "sender_username": "aylin",
            "recipient_id": "emp-2",
        }
    )

    await subscribers._notify_draft_shared(event)

    fake_service.create.assert_awaited_once()
    kwargs = fake_service.create.await_args.kwargs
    assert kwargs["company_id"] == "company-1"
    assert kwargs["user_id"] == "emp-2"
    assert kwargs["type"] == "draft_shared"
    assert "aylin" in kwargs["body"]
    assert kwargs["resource_type"] == "draft_share"
    assert kwargs["resource_id"] == "share-1"


async def test_draft_share_responded_notifies_the_sender(fake_service):
    event = DraftShareRespondedEvent(
        payload={
            "company_id": "company-1",
            "share_id": "share-1",
            "draft_id": "draft-1",
            "sender_id": "emp-1",
            "recipient_id": "emp-2",
            "recipient_username": "berk",
            "status": "accepted",
            "response_note": None,
        }
    )

    await subscribers._notify_draft_share_responded(event)

    kwargs = fake_service.create.await_args.kwargs
    assert kwargs["user_id"] == "emp-1"
    assert kwargs["type"] == "draft_share_responded"
    assert "berk" in kwargs["body"]
    assert "kabul etti" in kwargs["body"]


async def test_draft_share_responded_reports_rejection_verb(fake_service):
    event = DraftShareRespondedEvent(
        payload={
            "company_id": "company-1",
            "share_id": "share-1",
            "draft_id": "draft-1",
            "sender_id": "emp-1",
            "recipient_id": "emp-2",
            "recipient_username": "berk",
            "status": "rejected",
            "response_note": "olmadı",
        }
    )

    await subscribers._notify_draft_share_responded(event)

    kwargs = fake_service.create.await_args.kwargs
    assert "reddetti" in kwargs["body"]
