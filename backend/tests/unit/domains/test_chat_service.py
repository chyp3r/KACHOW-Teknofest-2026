"""Unit tests for ChatService's own draft-persistence guard, plus the
per-session lock serializing concurrent calls against the same thread_id
(C13/C14).

Only `_maybe_record_draft` and `_session_lock` are exercised directly here
-- a full `handle_message`/`resume` round trip needs a real compiled
planning graph, which belongs in the integration suite (see
tests/integration/test_hitl_flow.py and friends).
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.enums.step_status import StepStatus
from app.domains.chat.chat_service import ChatService, _session_lock


@pytest.mark.asyncio
async def test_a_failed_result_is_never_persisted_as_a_new_draft_version(monkeypatch):
    """C12 regression: `run_revise`'s FAILED return paths carry the
    *previous*, unrevised text back verbatim (see revise.py), stamped with
    a 0.0 confidence score that has nothing to do with that text's real
    quality. Persisting it created a phantom new version, byte-identical to
    the one before it but scored 0.0/FAILED, which
    DraftRepository.get_latest_for_session then served as "the current
    draft" ahead of the real one."""
    record_draft = AsyncMock(return_value="should-not-be-called")
    monkeypatch.setattr("app.domains.chat.chat_service.draft_recorder.record_draft", record_draft)

    service = ChatService(planning_graph=None)
    final_output = {
        "draft": {
            "draft": "Konu: Test\n\nArz ederim.",
            "status": StepStatus.FAILED,
            "confidence_score": 0.0,
        },
        "routing": {},
    }

    draft_id = await service._maybe_record_draft(
        final_output, config={}, thread_id="t1", user_id=None, document_id=None
    )

    assert draft_id is None
    record_draft.assert_not_called()


@pytest.mark.asyncio
async def test_a_completed_result_is_still_persisted(monkeypatch):
    """Control for the test above -- the FAILED guard must not swallow an
    ordinary successful draft/revision."""
    record_draft = AsyncMock(return_value="draft-123")
    monkeypatch.setattr("app.domains.chat.chat_service.draft_recorder.record_draft", record_draft)

    service = ChatService(planning_graph=None)
    final_output = {
        "draft": {
            "draft": "Konu: Test\n\nArz ederim.",
            "status": StepStatus.COMPLETED,
            "confidence_score": 92.0,
        },
        "routing": {},
    }

    class _FakeGraph:
        async def aupdate_state(self, *args, **kwargs):
            return None

    service.planning_graph = _FakeGraph()

    draft_id = await service._maybe_record_draft(
        final_output, config={}, thread_id="t1", user_id=None, document_id=None
    )

    assert draft_id == "draft-123"
    record_draft.assert_called_once()


@pytest.mark.asyncio
async def test_applied_rules_is_folded_into_the_stored_verification(monkeypatch):
    """C29: draft["verification"] alone only ever carries
    VerificationReport.applied_rules -- the deterministic verifier's own
    findings. The fuller, auditable breakdown (PII, judge/style findings,
    ...) lives in draft["applied_rules"] instead (see merge_verdicts's own
    docstring), and DraftModel.verification has no separate column for it
    -- this must be folded in before persisting, the same way
    DraftService's own verification_for_storage does."""
    record_draft = AsyncMock(return_value="draft-123")
    monkeypatch.setattr("app.domains.chat.chat_service.draft_recorder.record_draft", record_draft)

    service = ChatService(planning_graph=None)
    final_output = {
        "draft": {
            "draft": "Konu: Test\n\nArz ederim.",
            "status": StepStatus.COMPLETED,
            "confidence_score": 70.0,
            "verification": {"confidence_score": 70.0, "applied_rules": []},
            "applied_rules": [
                {"rule_id": "pii_bulgusu", "label": "Kişisel veri bulgusu",
                 "category": "gizlilik", "occurrences": 1, "penalty_applied": 15.0,
                 "forces_approval": True},
            ],
        },
        "routing": {},
    }

    class _FakeGraph:
        async def aupdate_state(self, *args, **kwargs):
            return None

    service.planning_graph = _FakeGraph()

    await service._maybe_record_draft(
        final_output, config={}, thread_id="t1", user_id=None, document_id=None
    )

    stored_verification = record_draft.call_args.kwargs["verification"]
    assert stored_verification["applied_rules"] == final_output["draft"]["applied_rules"]


# ==========================================
# _session_lock -- C13/C14
# ==========================================
def test_the_same_thread_id_always_returns_the_same_lock_instance():
    assert _session_lock("thread-a") is _session_lock("thread-a")


def test_different_thread_ids_get_independent_locks():
    assert _session_lock("thread-a") is not _session_lock("thread-b")


@pytest.mark.asyncio
async def test_two_concurrent_calls_for_the_same_session_are_serialized():
    """The core guarantee: two coroutines racing for the same thread_id's
    lock never overlap -- one fully finishes (enter and exit both recorded)
    before the other's own enter is recorded."""
    order: list[str] = []

    async def _turn(label: str) -> None:
        async with _session_lock("shared-thread"):
            order.append(f"{label}-enter")
            await asyncio.sleep(0.01)
            order.append(f"{label}-exit")

    await asyncio.gather(_turn("first"), _turn("second"))

    assert order in (
        ["first-enter", "first-exit", "second-enter", "second-exit"],
        ["second-enter", "second-exit", "first-enter", "first-exit"],
    )


@pytest.mark.asyncio
async def test_concurrent_calls_for_different_sessions_are_not_serialized():
    """Control for the test above -- two unrelated sessions must not block
    each other; only a shared thread_id does."""
    order: list[str] = []
    started_first = asyncio.Event()

    async def _first() -> None:
        async with _session_lock("thread-x"):
            order.append("first-enter")
            started_first.set()
            await asyncio.sleep(0.05)
            order.append("first-exit")

    async def _second() -> None:
        await started_first.wait()
        async with _session_lock("thread-y"):
            order.append("second-enter")
            order.append("second-exit")

    await asyncio.gather(_first(), _second())

    # "second" ran to completion while "first" was still holding its own,
    # unrelated lock -- proof the two sessions never contended.
    assert order.index("second-enter") < order.index("first-exit")
