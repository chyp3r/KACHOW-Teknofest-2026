"""Tests for the run-recording audit trail (Faz 6).

RUN_RECORDING_ENABLED is off globally in tests (see conftest.py's
`_disable_run_recording`), so every test here explicitly re-enables it and
stands in for `AsyncSessionLocal` with a mock session rather than hitting a
real database -- these test the recorder's own logic in isolation, not
Postgres itself (that's covered by the alembic migration verification done
by hand for this phase, same as Faz 4/5).
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability import run_recorder
from app.observability.model.run_model import RunModel


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
def enabled_session(monkeypatch, mock_session):
    """Turn recording on and point AsyncSessionLocal at a mock session."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", True)
    monkeypatch.setattr(
        run_recorder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )
    return mock_session


# ==========================================
# start_run
# ==========================================
@pytest.mark.asyncio
async def test_start_run_persists_the_full_plan_decision(enabled_session):
    await run_recorder.start_run(
        run_id="run-1",
        thread_id="user-1:s1",
        user_id="user-1",
        document_id="uploads/a.pdf",
        input_text="taslak hazırla",
        intent="draft",
        plan_steps=["classification", "draft"],
        source="scored",
        confidence=0.92,
        evidence=("draft.explicit_request",),
        alternatives=(("assist", 0.4),),
        clarification=None,
    )

    enabled_session.add.assert_called_once()
    run = enabled_session.add.call_args.args[0]
    assert isinstance(run, RunModel)
    assert run.id == "run-1"
    assert run.thread_id == "user-1:s1"
    assert run.user_id == "user-1"
    assert run.intent == "draft"
    assert run.plan_steps == ["classification", "draft"]
    assert run.evidence == ["draft.explicit_request"]
    assert run.alternatives == [["assist", 0.4]]
    assert run.status == "running"
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_run_is_a_noop_when_recording_is_disabled(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", False)
    monkeypatch.setattr(
        run_recorder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )

    await run_recorder.start_run(
        run_id="run-1",
        thread_id="s1",
        user_id=None,
        document_id=None,
        input_text="x",
        intent="assist",
        plan_steps=["assist"],
        source="scored",
        confidence=1.0,
        evidence=(),
        alternatives=(),
        clarification=None,
    )

    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_start_run_survives_a_database_failure(enabled_session):
    """Recording a run must never be the reason a chat turn fails."""
    enabled_session.commit.side_effect = Exception("db exploded")

    await run_recorder.start_run(
        run_id="run-1",
        thread_id="s1",
        user_id=None,
        document_id=None,
        input_text="x",
        intent="assist",
        plan_steps=["assist"],
        source="scored",
        confidence=1.0,
        evidence=(),
        alternatives=(),
        clarification=None,
    )
    # No exception propagated -- that's the whole test.


# ==========================================
# record_step
# ==========================================
@pytest.mark.asyncio
async def test_record_step_persists_status_and_duration(enabled_session):
    await run_recorder.record_step(
        run_id="run-1", step="draft", status="completed", duration_ms=1234.5
    )

    step = enabled_session.add.call_args.args[0]
    assert step.run_id == "run-1"
    assert step.step == "draft"
    assert step.status == "completed"
    assert step.duration_ms == 1234.5
    assert step.error is None
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_step_carries_the_error_message_on_failure(enabled_session):
    await run_recorder.record_step(
        run_id="run-1",
        step="draft",
        status="failed",
        duration_ms=50.0,
        error="ollama down",
    )

    step = enabled_session.add.call_args.args[0]
    assert step.status == "failed"
    assert step.error == "ollama down"


@pytest.mark.asyncio
async def test_record_step_is_a_noop_without_a_run_id(enabled_session):
    await run_recorder.record_step(
        run_id="", step="draft", status="completed", duration_ms=1.0
    )

    enabled_session.add.assert_not_called()


# ==========================================
# end_run
# ==========================================
@pytest.mark.asyncio
async def test_end_run_closes_out_the_run_status(enabled_session):
    run = RunModel(
        id="run-1",
        thread_id="s1",
        intent="draft",
        plan_steps=[],
        source="scored",
        evidence=[],
        alternatives=[],
        status="running",
    )
    enabled_session.get.return_value = run

    await run_recorder.end_run(run_id="run-1", status="completed")

    enabled_session.get.assert_awaited_once()
    assert run.status == "completed"
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_run_is_a_noop_when_the_run_row_is_missing(enabled_session):
    enabled_session.get.return_value = None

    await run_recorder.end_run(run_id="run-1", status="completed")

    enabled_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_end_run_is_a_noop_without_a_run_id(enabled_session):
    await run_recorder.end_run(run_id="", status="completed")

    enabled_session.get.assert_not_called()
