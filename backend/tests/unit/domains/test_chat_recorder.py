"""Unit tests for the best-effort chat history recorder (app.domains.chat.chat_recorder).

`CHAT_HISTORY_ENABLED` is off globally in tests (see conftest.py's
`_disable_chat_history_recording`), so every test here explicitly re-enables
it and stands in for `tenant_session` with a mock session the same way
tests/unit/test_run_recorder.py does for its own sibling recorder --
`ChatSessionRepository`/`ChatMessageRepository` are mocked directly rather
than exercised against the mock session, since this file tests
`record_turn`'s own control flow (does it call the right repository methods
in the right order, does it swallow its own failures), not the
repositories' internals.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat import chat_recorder


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def repos(monkeypatch):
    """Stand in for both repository classes `record_turn` constructs."""
    session_repo = AsyncMock()
    message_repo = AsyncMock()
    monkeypatch.setattr(chat_recorder, "ChatSessionRepository", MagicMock(return_value=session_repo))
    monkeypatch.setattr(chat_recorder, "ChatMessageRepository", MagicMock(return_value=message_repo))
    return session_repo, message_repo


@pytest.fixture
def enabled_session(monkeypatch, mock_session):
    """Turn recording on and point tenant_session at a mock session."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_HISTORY_ENABLED", True)
    monkeypatch.setattr(
        chat_recorder,
        "tenant_session",
        lambda company_id=None: _FakeSessionContext(mock_session),
    )
    return mock_session


# ==========================================
# record_turn
# ==========================================
@pytest.mark.asyncio
async def test_record_turn_is_a_no_op_when_history_is_disabled(mock_session, repos, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_HISTORY_ENABLED", False)
    session_repo, message_repo = repos

    await chat_recorder.record_turn(
        thread_id="t1",
        user_id="u1",
        document_id=None,
        user_message="soru",
        reply="cevap",
        workflow_status="COMPLETED",
        details=None,
    )

    session_repo.get_or_create.assert_not_awaited()
    message_repo.add_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_turn_persists_the_session_and_both_messages(enabled_session, repos):
    session_repo, message_repo = repos

    await chat_recorder.record_turn(
        thread_id="t1",
        user_id="u1",
        document_id="uploads/a.pdf",
        user_message="Bu evrağı özetle",
        user_details={"foo": "bar"},
        reply="İşte özet.",
        workflow_status="COMPLETED",
        details={"intent": "assist"},
        company_id="company-1",
    )

    session_repo.get_or_create.assert_awaited_once_with(
        "t1",
        user_id="u1",
        company_id="company-1",
        document_id="uploads/a.pdf",
        title="Bu evrağı özetle",
    )
    assert message_repo.add_message.await_count == 2
    user_call, assistant_call = message_repo.add_message.await_args_list
    assert user_call.kwargs["role"] == "user"
    assert user_call.kwargs["content"] == "Bu evrağı özetle"
    assert user_call.kwargs["details"] == {"foo": "bar"}
    assert assistant_call.kwargs["role"] == "assistant"
    assert assistant_call.kwargs["content"] == "İşte özet."
    assert assistant_call.kwargs["workflow_status"] == "COMPLETED"
    assert assistant_call.kwargs["details"] == {"intent": "assist"}
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_turn_swallows_a_failure_instead_of_raising(enabled_session, repos, caplog):
    """A chat turn's own success must never depend on whether recording it
    for the history sidebar happened to work."""
    session_repo, _ = repos
    session_repo.get_or_create.side_effect = Exception("db exploded")

    with caplog.at_level("ERROR"):
        await chat_recorder.record_turn(
            thread_id="t1",
            user_id="u1",
            document_id=None,
            user_message="soru",
            reply="cevap",
            workflow_status="COMPLETED",
            details=None,
        )

    assert "t1" in caplog.text


# ==========================================
# _derive_title
# ==========================================
def test_derive_title_returns_short_messages_unchanged():
    assert chat_recorder._derive_title("Merhaba, nasılsın?") == "Merhaba, nasılsın?"


def test_derive_title_collapses_internal_whitespace():
    assert chat_recorder._derive_title("Bu   evrağı\n\nözetle   lütfen") == "Bu evrağı özetle lütfen"


def test_derive_title_truncates_long_messages_with_an_ellipsis():
    long_message = "kelime " * 30  # far past the default 80-char cutoff
    title = chat_recorder._derive_title(long_message)

    assert len(title) == 80
    assert title.endswith("…")


def test_derive_title_respects_a_custom_max_length():
    title = chat_recorder._derive_title("bu tam on iki karakter", max_length=10)

    assert len(title) == 10
    assert title.endswith("…")
