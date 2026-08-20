"""Unit tests for ChatService's own draft-persistence guard.

Only `_maybe_record_draft` is exercised here -- everything else on
ChatService needs a real compiled planning graph, which belongs in the
integration suite (see tests/integration/test_hitl_flow.py and friends).
"""

from unittest.mock import AsyncMock

import pytest

from app.core.enums.step_status import StepStatus
from app.domains.chat.chat_service import ChatService


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
