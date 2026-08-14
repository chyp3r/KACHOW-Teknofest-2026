"""Shared fixtures for tests that need a real, RLS-enabled Postgres database.

Every other test in this repo mocks the DB session entirely (see
``tests/conftest.py``'s own module docstring) -- which cannot prove row
-level security does anything: an ``AsyncMock`` returns whatever a test
tells it to regardless of which Postgres role is asking, so a test written
against one would pass identically against a completely broken RLS policy.
This package is the deliberate exception, per the tenancy plan's own
diagnosis of that gap (§10): a real Postgres, the real migration chain
(including ``0013_rls``), and two real connection roles.

**No testcontainers.** ``make test`` already runs *inside* the ``backend``
container; giving it access to the Docker socket to spin up more containers
would be a real security/portability change for a repo that doesn't need
it -- the compose ``db`` service (``pgvector/pgvector:pg16``, the same image
production runs) is already reachable at ``db:5432`` from here. A throwaway
database on that same server is enough isolation for these tests without
adding a new moving part.

One throwaway ``kachow_test_<hex>`` database per test *session* (not per
test): migrating it through the full ``0001``..``0013`` chain via a real
``alembic upgrade head`` subprocess is what makes ``0013_rls`` the actual
thing under test rather than a hand-rolled approximation of it, and paying
that cost once instead of per test keeps this suite fast enough to run on
every plain `pytest` invocation -- this repo has no separate CI-only
integration lane (see the ``integration`` marker's docstring in
``pyproject.toml``).

Engines are function-scoped, not session-scoped, on purpose: an
``AsyncSession``'s connection pool is bound to the event loop that created
it, and pytest-asyncio gives each test its own loop by default -- reusing a
session-scoped engine across tests would hit the exact "attached to a
different loop" failure ``tests/conftest.py``'s
``_reset_redis_cache_between_tests`` fixture already documents for Redis.
"""

import asyncio
import os
import subprocess
import uuid
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

#: backend/ -- where alembic.ini lives. This file is backend/tests/integration/conftest.py.
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    """``postgresql+asyncpg://...`` -> ``postgresql://...`` (asyncpg.connect wants a plain DSN)."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


def _with_database(url: str, database: str) -> str:
    """Swap the database name in a ``postgresql[+asyncpg]://...`` URL."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


@pytest.fixture(scope="session")
def pg_test_database() -> str:
    """Create a throwaway database, migrated to head, dropped at session end.

    A plain sync fixture on purpose: it only ever runs its own short-lived
    ``asyncio.run()`` calls internally (never awaited from, or interleaved
    with, a test's own event loop), so it carries none of the cross-loop
    risk a session-scoped *async* fixture would.
    """
    owner_admin_url = settings.effective_alembic_database_url
    db_name = f"kachow_test_{uuid.uuid4().hex[:12]}"

    async def _create() -> None:
        conn = await asyncpg.connect(dsn=_asyncpg_dsn(owner_admin_url))
        try:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()

    asyncio.run(_create())

    test_db_owner_url = _with_database(owner_admin_url, db_name)
    env = {**os.environ, "DATABASE_URL": test_db_owner_url, "ALEMBIC_DATABASE_URL": test_db_owner_url}
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(_BACKEND_DIR),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    yield db_name

    async def _drop() -> None:
        conn = await asyncpg.connect(dsn=_asyncpg_dsn(owner_admin_url))
        try:
            # A lingering connection (a fixture that failed to dispose its
            # engine) would otherwise block DROP DATABASE outright.
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                db_name,
            )
            await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        finally:
            await conn.close()

    asyncio.run(_drop())


@pytest.fixture
async def owner_engine(pg_test_database: str) -> AsyncGenerator:
    """An async engine on the test database, connected as its schema owner.

    Bypasses row-level security entirely (owner connections always do --
    see migration ``0013_rls``'s own module docstring) -- used for
    convenient, RLS-agnostic test-data setup (``two_companies`` below) and
    for ``test_rls_role_is_not_owner.py``'s own contrast case.
    """
    owner_url = _with_database(settings.effective_alembic_database_url, pg_test_database)
    engine = create_async_engine(owner_url, future=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def app_engine(pg_test_database: str) -> AsyncGenerator:
    """An async engine on the test database, connected as the restricted ``kachow_app`` role.

    Every RLS assertion in this package goes through this engine, never
    ``owner_engine`` -- that is the entire point (see this module's own
    docstring).
    """
    app_url = _with_database(
        f"postgresql+asyncpg://kachow_app:{settings.KACHOW_APP_DB_PASSWORD}@"
        f"{urlsplit(settings.effective_alembic_database_url).hostname}:"
        f"{urlsplit(settings.effective_alembic_database_url).port}",
        pg_test_database,
    )
    engine = create_async_engine(app_url, future=True, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def app_session(engine, company_id, is_root: bool = False) -> AsyncSession:
    """Open a session on ``app_engine`` with the tenant GUCs already set.

    Mirrors ``app.infrastructure.database.session._apply_tenant_guc`` --
    deliberately re-implemented here rather than imported, so these tests
    exercise the same *SQL* the production helper issues without coupling
    to its Python call signature (the assertion this package cares about is
    "does Postgres itself enforce this", not "does this function get
    called").

    Caller owns closing the returned session.
    """
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = session_maker()
    await session.execute(
        text("SELECT set_config('app.current_company_id', :cid, true)"),
        {"cid": company_id or ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_root', :v, true)"),
        {"v": "on" if is_root else "off"},
    )
    return session


@pytest.fixture
async def two_companies(owner_engine) -> AsyncGenerator[dict, None]:
    """Two companies, each with one user, one document, one unit, one unit
    membership, one draft, one draft_share (self-addressed -- see below) and
    one notification, inserted via the owner connection.

    Returns a dict: ``{"a": {"company_id", "user_id", "document_id", "unit_id",
    "membership_id", "draft_id", "draft_share_id", "notification_id"}, "b":
    {...}}``. Uses ``owner_engine`` (not RLS'd) purely as convenient, trusted
    test-data setup -- what's actually under test in this package is whether
    the *app* role can cross from A into B, never whether the owner can (it
    always can, by definition).
    """
    session_maker = async_sessionmaker(bind=owner_engine, class_=AsyncSession, expire_on_commit=False)
    result: dict = {}
    async with session_maker() as session:
        for label in ("a", "b"):
            company_id = uuid4().hex
            user_id = uuid4().hex
            document_id = f"uploads/rls-test-{uuid4().hex}.pdf"
            await session.execute(
                text(
                    "INSERT INTO companies (id, name, slug, is_active, is_deleted, settings, created_at, updated_at) "
                    "VALUES (:id, :name, :slug, true, false, '{}', now(), now())"
                ),
                {"id": company_id, "name": f"RLS Test Co {label.upper()}", "slug": f"rls-test-{label}-{uuid4().hex[:8]}"},
            )
            await session.execute(
                text(
                    "INSERT INTO users (id, company_id, username, email, hashed_password, role, "
                    "clearance_level, is_active, is_deleted, created_at, updated_at) "
                    "VALUES (:id, :cid, :username, :email, 'x', 'employee', 'hizmete_ozel', true, false, now(), now())"
                ),
                {
                    "id": user_id,
                    "cid": company_id,
                    "username": f"rls-test-{label}-{uuid4().hex[:8]}",
                    "email": f"rls-test-{label}-{uuid4().hex[:8]}@kachow.example",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO documents (id, company_id, owner_id, file_name, created_at, updated_at) "
                    "VALUES (:id, :cid, :uid, :fname, now(), now())"
                ),
                {"id": document_id, "cid": company_id, "uid": user_id, "fname": f"{label}.pdf"},
            )

            unit_id = uuid4().hex
            membership_id = uuid4().hex
            await session.execute(
                text(
                    "INSERT INTO units (id, company_id, name, description, is_active, created_at, updated_at) "
                    "VALUES (:id, :cid, :name, 'desc', true, now(), now())"
                ),
                {"id": unit_id, "cid": company_id, "name": f"RLS Test Unit {label.upper()}"},
            )
            await session.execute(
                text(
                    "INSERT INTO unit_memberships (id, company_id, unit_id, user_id, is_primary, created_at, updated_at) "
                    "VALUES (:id, :cid, :uid, :userid, false, now(), now())"
                ),
                {"id": membership_id, "cid": company_id, "uid": unit_id, "userid": user_id},
            )

            draft_id = uuid4().hex
            await session.execute(
                text(
                    "INSERT INTO drafts (id, company_id, user_id, version, content, is_deleted, created_at, updated_at) "
                    "VALUES (:id, :cid, :uid, 1, 'içerik', false, now(), now())"
                ),
                {"id": draft_id, "cid": company_id, "uid": user_id},
            )

            #: Self-addressed (sender == recipient) purely so this fixture
            #: doesn't need a second user per company -- the RLS tests below
            #: only care about company_id boundaries, not the sender/
            #: recipient distinction `draft_shares`' own business logic cares
            #: about (see `DraftShareService`).
            draft_share_id = uuid4().hex
            await session.execute(
                text(
                    "INSERT INTO draft_shares (id, company_id, draft_id, sender_id, recipient_id, "
                    "status, created_at, updated_at) "
                    "VALUES (:id, :cid, :did, :uid, :uid, 'sent', now(), now())"
                ),
                {"id": draft_share_id, "cid": company_id, "did": draft_id, "uid": user_id},
            )

            notification_id = uuid4().hex
            await session.execute(
                text(
                    "INSERT INTO notifications (id, company_id, user_id, type, title, created_at, updated_at) "
                    "VALUES (:id, :cid, :uid, 'draft_shared', 'Test', now(), now())"
                ),
                {"id": notification_id, "cid": company_id, "uid": user_id},
            )

            result[label] = {
                "company_id": company_id,
                "user_id": user_id,
                "document_id": document_id,
                "unit_id": unit_id,
                "membership_id": membership_id,
                "draft_id": draft_id,
                "draft_share_id": draft_share_id,
                "notification_id": notification_id,
            }
        await session.commit()

    yield result
