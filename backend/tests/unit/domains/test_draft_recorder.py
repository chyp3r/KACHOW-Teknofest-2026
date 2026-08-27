"""Unit tests for app.domains.drafts.draft_recorder.record_draft.

Focus: a ``revise`` chat turn's plan is ``["revise"]`` only -- no ``routing``
step -- so ``chat_service._maybe_record_draft`` calls ``record_draft`` with
``destination=None``. The birim önerisi must then be carried over from the
previous version instead of being reset to blank on every revision.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.domains.drafts import draft_recorder


@pytest.fixture(autouse=True)
def _enable_draft_history(monkeypatch):
    """tests/conftest.py bir autouse fixture ile DRAFT_HISTORY_ENABLED'ı
    kapatır; bu modül tam da o yazma yolunu test ettiği için geri açar."""
    monkeypatch.setattr(settings, "DRAFT_HISTORY_ENABLED", True)


class _Parent:
    id = "v1"
    version = 1
    destination = "İnsan Kaynakları Müdürlüğü"
    destination_unit_id = "unit-hr"
    destination_justification = "Konu personel özlük işleridir."


@pytest.fixture
def _patched(monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def _fake_tenant_session(_company_id):
        yield session

    repo = MagicMock()
    repo.get_latest_for_session = AsyncMock(return_value=_Parent())
    repo.create_version = AsyncMock(return_value=MagicMock(id="v2"))

    unit_repo = MagicMock()
    unit_repo.get_by_name = AsyncMock(return_value=MagicMock(id="unit-hr"))

    monkeypatch.setattr(draft_recorder, "tenant_session", _fake_tenant_session)
    monkeypatch.setattr(draft_recorder, "DraftRepository", lambda _s: repo)
    monkeypatch.setattr(draft_recorder, "UnitRepository", lambda _s: unit_repo)
    return repo


@pytest.mark.asyncio
async def test_revision_inherits_the_previous_versions_birim_onerisi(_patched):
    await draft_recorder.record_draft(
        user_id="emp-1",
        session_id="sess-1",
        document_id=None,
        content="revize edilmiş taslak",
        destination=None,
        destination_justification=None,
        company_id="company-1",
    )

    kwargs = _patched.create_version.await_args.kwargs
    assert kwargs["destination"] == "İnsan Kaynakları Müdürlüğü"
    assert kwargs["destination_unit_id"] == "unit-hr"
    assert kwargs["destination_justification"] == "Konu personel özlük işleridir."


@pytest.mark.asyncio
async def test_a_fresh_routing_result_is_not_overwritten_by_the_parent(_patched):
    await draft_recorder.record_draft(
        user_id="emp-1",
        session_id="sess-1",
        document_id=None,
        content="yeni taslak",
        destination="Hukuk Müşavirliği",
        destination_justification="Konu hukuki görüş talebidir.",
        company_id="company-1",
    )

    kwargs = _patched.create_version.await_args.kwargs
    assert kwargs["destination"] == "Hukuk Müşavirliği"
    assert kwargs["destination_justification"] == "Konu hukuki görüş talebidir."


@pytest.mark.asyncio
async def test_unit_id_falls_back_to_parent_when_it_cannot_be_resolved(monkeypatch):
    session = AsyncMock()

    @asynccontextmanager
    async def _fake_tenant_session(_company_id):
        yield session

    repo = MagicMock()
    repo.get_latest_for_session = AsyncMock(return_value=_Parent())
    repo.create_version = AsyncMock(return_value=MagicMock(id="v2"))
    unit_repo = MagicMock()
    unit_repo.get_by_name = AsyncMock(return_value=None)  # birim yeniden adlandırıldı

    monkeypatch.setattr(draft_recorder, "tenant_session", _fake_tenant_session)
    monkeypatch.setattr(draft_recorder, "DraftRepository", lambda _s: repo)
    monkeypatch.setattr(draft_recorder, "UnitRepository", lambda _s: unit_repo)

    await draft_recorder.record_draft(
        user_id="emp-1",
        session_id="sess-1",
        document_id=None,
        content="revize",
        destination=None,
        company_id="company-1",
    )

    kwargs = repo.create_version.await_args.kwargs
    assert kwargs["destination"] == "İnsan Kaynakları Müdürlüğü"
    assert kwargs["destination_unit_id"] == "unit-hr"
