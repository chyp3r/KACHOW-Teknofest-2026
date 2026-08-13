"""Tests for the default ADMIN/MANAGER/EMPLOYEE account bootstrap.

SEED_DEFAULT_USERS is off globally in tests (see conftest.py's
`_disable_default_user_seeding`), so every test here explicitly re-enables
it and stands in for `AsyncSessionLocal` with a mock session rather than
hitting a real database -- same approach as test_run_recorder.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users import seeder
from app.domains.users.model.user_model import UserModel


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc_info):
        return False


def _result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture
def mock_session():
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def enabled_session(monkeypatch, mock_session):
    """Turn seeding on and point AsyncSessionLocal at a mock session."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_USERS", True)
    monkeypatch.setattr(
        seeder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )
    return mock_session


_ACCOUNT = seeder._SeedAccount(
    username="admin",
    email="admin@kachow.local",
    password="Admin123!",
    role="admin",
    company_id="company-1",
)


# ==========================================
# _seed_accounts
# ==========================================
def test_seed_accounts_uses_configured_credentials(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_ADMIN_EMAIL", "custom-admin@x.com")
    monkeypatch.setattr(settings, "SEED_ADMIN_PASSWORD", "custom-pw")

    accounts = seeder._seed_accounts("company-1")

    assert {a.role for a in accounts} == {"root", "admin", "manager", "employee"}
    admin = next(a for a in accounts if a.role == "admin")
    assert admin.username == "admin"
    assert admin.email == "custom-admin@x.com"
    assert admin.password == "custom-pw"
    assert admin.company_id == "company-1"

    root = next(a for a in accounts if a.role == "root")
    assert root.company_id is None


def test_seed_accounts_seeds_only_root_without_a_company():
    accounts = seeder._seed_accounts(None)

    assert {a.role for a in accounts} == {"root"}


# ==========================================
# _seed_one
# ==========================================
@pytest.mark.asyncio
async def test_seed_one_creates_the_account_when_missing(enabled_session):
    enabled_session.execute.side_effect = [_result(None), _result(None)]

    created = await seeder._seed_one(_ACCOUNT)

    assert created is True
    enabled_session.add.assert_called_once()
    user = enabled_session.add.call_args.args[0]
    assert isinstance(user, UserModel)
    assert user.username == "admin"
    assert user.email == "admin@kachow.local"
    assert user.role == "admin"
    assert user.is_active is True
    assert user.is_deleted is False
    # Stored as a bcrypt hash, never the plaintext password.
    assert user.hashed_password != _ACCOUNT.password
    enabled_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_seed_one_skips_when_email_already_exists(enabled_session):
    existing = UserModel(
        id="u1",
        username="someone-else",
        email="admin@kachow.local",
        role="admin",
        is_active=True,
        is_deleted=False,
        hashed_password="x",
    )
    enabled_session.execute.side_effect = [_result(existing)]

    created = await seeder._seed_one(_ACCOUNT)

    assert created is False
    enabled_session.add.assert_not_called()
    enabled_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_seed_one_skips_when_username_taken_by_a_different_email(enabled_session):
    conflicting = UserModel(
        id="u2",
        username="admin",
        email="someone@else.com",
        role="employee",
        is_active=True,
        is_deleted=False,
        hashed_password="x",
    )
    enabled_session.execute.side_effect = [_result(None), _result(conflicting)]

    created = await seeder._seed_one(_ACCOUNT)

    assert created is False
    enabled_session.add.assert_not_called()
    enabled_session.commit.assert_not_called()


# ==========================================
# seed_default_users
# ==========================================
@pytest.mark.asyncio
async def test_seed_default_users_is_a_noop_when_disabled(monkeypatch, mock_session):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_USERS", False)
    monkeypatch.setattr(
        seeder, "AsyncSessionLocal", lambda: _FakeSessionContext(mock_session)
    )

    await seeder.seed_default_users("company-1")

    mock_session.execute.assert_not_called()
    mock_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_seed_default_users_creates_one_account_per_role(enabled_session):
    enabled_session.execute.return_value = _result(None)

    await seeder.seed_default_users("company-1")

    assert enabled_session.add.call_count == 4
    roles = {call.args[0].role for call in enabled_session.add.call_args_list}
    assert roles == {"root", "admin", "manager", "employee"}
    assert enabled_session.commit.await_count == 4


@pytest.mark.asyncio
async def test_seed_default_users_tolerates_one_account_failing(monkeypatch, enabled_session):
    """One account's DB error must not stop the others from being seeded."""
    calls = []

    async def fake_seed_one(account):
        calls.append(account.role)
        if account.role == "manager":
            raise Exception("db exploded")
        return True

    monkeypatch.setattr(seeder, "_seed_one", fake_seed_one)

    await seeder.seed_default_users("company-1")

    assert calls == ["root", "admin", "manager", "employee"]
