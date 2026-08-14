"""Tests for the guardrail decision audit trail and its metric (Faz 5).

RUN_RECORDING_ENABLED is off globally in tests (see conftest.py's
`_disable_run_recording`), matching test_run_recorder.py's own setup --
these test the recorder's own logic in isolation, not Postgres itself.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability import guardrail_recorder
from app.observability.ai_metrics import GUARDRAIL_DECISIONS
from app.observability.model.guardrail_model import GuardrailEventModel


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
    """Turn recording on and point tenant_session at a mock session."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", True)
    monkeypatch.setattr(
        guardrail_recorder,
        "tenant_session",
        lambda company_id=None, is_root=False: _FakeSessionContext(mock_session),
    )
    return mock_session


def _counter_value(stage: str, kind: str, decision: str) -> float:
    return GUARDRAIL_DECISIONS.labels(stage=stage, kind=kind, decision=decision)._value.get()


# ==========================================
# GUARDRAIL_DECISIONS -- unconditional, independent of RUN_RECORDING_ENABLED
# ==========================================
@pytest.mark.asyncio
async def test_record_event_increments_the_counter_for_its_stage_kind_and_decision(
    enabled_session,
):
    before = _counter_value("input", "pii", "flagged")

    await guardrail_recorder.record_event(stage="input", kind="pii", decision="flagged")

    assert _counter_value("input", "pii", "flagged") == before + 1


@pytest.mark.asyncio
async def test_record_event_increments_the_counter_even_when_recording_is_disabled(
    monkeypatch, mock_session
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", False)
    monkeypatch.setattr(
        guardrail_recorder,
        "tenant_session",
        lambda company_id=None, is_root=False: _FakeSessionContext(mock_session),
    )
    before = _counter_value("output", "leakage", "blocked")

    await guardrail_recorder.record_event(stage="output", kind="leakage", decision="blocked")

    assert _counter_value("output", "leakage", "blocked") == before + 1
    # The metric is unconditional, but the DB write still isn't.
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_record_event_counter_labels_do_not_bleed_into_each_other(enabled_session):
    before_flagged = _counter_value("input", "sensitivity", "flagged")
    before_passed = _counter_value("input", "sensitivity", "passed")

    await guardrail_recorder.record_event(stage="input", kind="sensitivity", decision="flagged")

    assert _counter_value("input", "sensitivity", "flagged") == before_flagged + 1
    assert _counter_value("input", "sensitivity", "passed") == before_passed


# ==========================================
# DB persistence (RUN_RECORDING_ENABLED)
# ==========================================
@pytest.mark.asyncio
async def test_record_event_persists_the_full_audit_row(enabled_session):
    await guardrail_recorder.record_event(
        stage="output",
        kind="leakage",
        decision="redacted",
        confidence=0.7,
        reasons=["Kaynak evrakta desteklenmeyen iddia."],
        run_id="run-1",
        document_id="uploads/a.pdf",
        requester_user_id="user-1",
        requester_role="employee",
        effective_clearance="ozel",
        related_document_ids=["uploads/a.pdf"],
        llm_model_version="qwen3.5:9b",
        prompt_template_version="abc123",
    )

    enabled_session.add.assert_called_once()
    event = enabled_session.add.call_args.args[0]
    assert isinstance(event, GuardrailEventModel)
    assert event.stage == "output"
    assert event.kind == "leakage"
    assert event.decision == "redacted"
    assert event.confidence == 0.7
    assert event.reasons == ["Kaynak evrakta desteklenmeyen iddia."]
    assert event.run_id == "run-1"
    assert event.document_id == "uploads/a.pdf"
    assert event.requester_user_id == "user-1"
    assert event.requester_role == "employee"
    assert event.effective_clearance == "ozel"
    assert event.related_document_ids == ["uploads/a.pdf"]
    assert event.llm_model_version == "qwen3.5:9b"
    assert event.prompt_template_version == "abc123"
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_event_is_a_noop_when_recording_is_disabled(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUN_RECORDING_ENABLED", False)
    monkeypatch.setattr(
        guardrail_recorder,
        "tenant_session",
        lambda company_id=None, is_root=False: _FakeSessionContext(mock_session),
    )

    await guardrail_recorder.record_event(stage="input", kind="pii", decision="flagged")

    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_record_event_survives_a_database_failure(enabled_session):
    """Recording a guardrail decision must never be the reason a request fails."""
    enabled_session.commit.side_effect = Exception("db exploded")

    await guardrail_recorder.record_event(stage="input", kind="pii", decision="flagged")
    # No exception propagated -- that's the whole test.
