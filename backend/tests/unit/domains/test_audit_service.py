from unittest.mock import AsyncMock

import pytest

from app.domains.audit.model.audit_log_model import AuditLogModel
from app.domains.audit.repository import GENESIS_HASH, compute_hash, hashable_fields
from app.domains.audit.service import AuditService


def _row(*, company_id, seq, prev_hash, action="unit:manage", **overrides):
    row = AuditLogModel(
        id=f"row-{seq}",
        company_id=company_id,
        seq=seq,
        actor_user_id=overrides.get("actor_user_id", "user-1"),
        actor_role=overrides.get("actor_role", "admin"),
        acting_as_company_id=None,
        action=action,
        resource_type=overrides.get("resource_type"),
        resource_id=overrides.get("resource_id"),
        decision=overrides.get("decision", "permit"),
        reason=overrides.get("reason"),
        before=overrides.get("before"),
        after=overrides.get("after"),
        ip=overrides.get("ip"),
        correlation_id=overrides.get("correlation_id"),
        prev_hash=prev_hash,
    )
    row.hash = compute_hash(prev_hash, hashable_fields(row))
    return row


def _chain(company_id, count):
    rows = []
    prev = GENESIS_HASH
    for seq in range(1, count + 1):
        row = _row(company_id=company_id, seq=seq, prev_hash=prev, resource_id=f"res-{seq}")
        rows.append(row)
        prev = row.hash
    return rows


@pytest.fixture
def mock_repo():
    return AsyncMock()


@pytest.fixture
def service(mock_repo):
    return AuditService(mock_repo)


@pytest.mark.asyncio
async def test_verify_chain_valid_chain_is_reported_valid(service, mock_repo):
    mock_repo.list_chain.return_value = _chain("company-a", 5)

    result = await service.verify_chain("company-a")

    assert result.valid is True
    assert result.rows_checked == 5
    assert result.broken_at_seq is None


@pytest.mark.asyncio
async def test_verify_chain_empty_chain_is_vacuously_valid(service, mock_repo):
    mock_repo.list_chain.return_value = []

    result = await service.verify_chain("company-a")

    assert result.valid is True
    assert result.rows_checked == 0


@pytest.mark.asyncio
async def test_verify_chain_detects_a_tampered_field(service, mock_repo):
    """Editing a row's own field (not its hash) after the fact must be
    caught -- the whole point of covering `resource_id` etc. in the hash."""
    rows = _chain("company-a", 3)
    rows[1].resource_id = "tampered"  # hash on this row no longer matches its fields

    mock_repo.list_chain.return_value = rows

    result = await service.verify_chain("company-a")

    assert result.valid is False
    assert result.broken_at_seq == 2
    assert "kendi alanlarından" in result.reason


@pytest.mark.asyncio
async def test_verify_chain_detects_a_row_spliced_out_of_the_middle(service, mock_repo):
    """Deleting/reordering a row breaks prev_hash continuity even though
    every remaining row's own hash is still internally self-consistent."""
    rows = _chain("company-a", 4)
    del rows[1]  # remove seq=2; seq=3's prev_hash no longer matches seq=1's hash

    mock_repo.list_chain.return_value = rows

    result = await service.verify_chain("company-a")

    assert result.valid is False
    assert result.broken_at_seq == 3
    assert "önceki satırın hash'iyle" in result.reason


@pytest.mark.asyncio
async def test_verify_chain_covers_the_null_company_system_chain_too(service, mock_repo):
    mock_repo.list_chain.return_value = _chain(None, 2)

    result = await service.verify_chain(None)

    assert result.valid is True
    mock_repo.list_chain.assert_awaited_once_with(None)


def test_compute_hash_is_sensitive_to_every_hashed_field():
    row = _row(company_id="c1", seq=1, prev_hash=GENESIS_HASH, reason="orijinal")
    original = compute_hash(row.prev_hash, hashable_fields(row))

    row.reason = "değiştirildi"
    tampered = compute_hash(row.prev_hash, hashable_fields(row))

    assert original != tampered


def test_compute_hash_is_sensitive_to_prev_hash():
    row = _row(company_id="c1", seq=2, prev_hash=GENESIS_HASH)
    with_genesis = compute_hash(row.prev_hash, hashable_fields(row))
    with_other_prev = compute_hash("f" * 64, hashable_fields(row))

    assert with_genesis != with_other_prev


@pytest.mark.asyncio
async def test_record_swallows_repository_failures(service, monkeypatch):
    """A DB hiccup while writing an audit row must not propagate -- see
    AuditService's module docstring on why this is fire-and-forget."""

    class _ExplodingContext:
        async def __aenter__(self):
            raise RuntimeError("db unavailable")

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(
        "app.domains.audit.service.tenant_session", lambda company_id, is_root=False: _ExplodingContext()
    )

    await service.record(
        company_id="company-a",
        actor_user_id="user-1",
        actor_role="admin",
        action="unit:manage",
    )
    # No exception raised -- that is the assertion.
