"""Backfill company_id on any pre-existing rows, into a synthesized "legacy" company.

Pure data migration -- no schema changes, only UPDATE/INSERT statements.
Written to be idempotent and restartable: every UPDATE is scoped to `WHERE
company_id IS NULL`, so re-running this after a partial failure only ever
touches the rows still unassigned.

On a fresh `make bootstrap` (the jury-facing path) every table this touches
is empty, so this migration is a fast no-op -- there is nothing to backfill,
and no "legacy" company or user is created. It only does real work against a
database that already had rows before the multi-tenancy migration landed
(a developer's pre-existing local DB, for example).

Deliberately NOT the same company as `app.domains.companies.seeder`'s
"demo" company: that one is created by the *application* at boot, which
runs after migrations, not before -- a migration cannot depend on
app-level seeding having already happened. The "legacy" company created
here (slug `legacy-pre-tenancy`) exists purely so `0011_tenancy_
constraints` has something to point every old row's company_id at before
turning the column NOT NULL.

`runs`, `run_steps`, `guardrail_events` are deliberately left unbackfilled:
those tables are written from deep inside the LangGraph orchestration layer,
which does not yet carry `company_id` through its state (see `RunModel.
company_id`'s docstring) -- their column stays nullable and unenforced until
that threading work lands (Faz 3), so there is nothing meaningful to backfill
them to yet. `chat_sessions`/`chat_messages`/`drafts` are backfilled on a
best-effort basis (assigned to the legacy company where a pre-existing row
exists) since doing so is cheap and harmless, but their NOT NULL enforcement
is likewise deferred to Faz 3.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-13

"""
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_COMPANY_SLUG = "legacy-pre-tenancy"
#: `.example` (RFC 2606), not `.local` -- see `settings.SEED_ROOT_EMAIL`'s
#: docstring for why `.local` fails `EmailStr` validation the moment this
#: row round-trips through a real API response.
_LEGACY_USER_EMAIL = "legacy-owner@kachow.example"
#: bcrypt hash of a random, never-used string -- this account exists only
#: as an FK target for orphaned pre-tenancy documents, not to be logged
#: into. Rotating/removing SECRET_KEY does not help here anyway, so a
#: fixed placeholder hash is fine.
_LEGACY_USER_HASH = "$2b$12$x89lcF4VezDSwEgE6rgJsuDYL.fxmT7bx3aGF9LJWYr4tBqXjS.MO"


def _any_unassigned(bind, table: str) -> bool:
    return bind.execute(
        text(f"SELECT 1 FROM {table} WHERE company_id IS NULL LIMIT 1")
    ).first() is not None


def _get_or_create_legacy_company(bind) -> str:
    existing = bind.execute(
        text("SELECT id FROM companies WHERE slug = :slug"),
        {"slug": _LEGACY_COMPANY_SLUG},
    ).first()
    if existing is not None:
        return existing[0]

    company_id = uuid4().hex
    bind.execute(
        text(
            "INSERT INTO companies (id, name, slug, is_active, is_deleted, settings, created_at, updated_at) "
            "VALUES (:id, :name, :slug, true, false, '{}', now(), now())"
        ),
        {
            "id": company_id,
            "name": "Eski Kayıtlar (Kiracı Öncesi)",
            "slug": _LEGACY_COMPANY_SLUG,
        },
    )
    return company_id


def _get_or_create_legacy_owner(bind, company_id: str) -> str:
    existing = bind.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": _LEGACY_USER_EMAIL},
    ).first()
    if existing is not None:
        return existing[0]

    user_id = uuid4().hex
    bind.execute(
        text(
            "INSERT INTO users (id, company_id, username, email, hashed_password, role, "
            "clearance_level, is_active, is_deleted, created_at, updated_at) "
            "VALUES (:id, :company_id, :username, :email, :hashed_password, 'employee', "
            "'hizmete_ozel', false, false, now(), now())"
        ),
        {
            "id": user_id,
            "company_id": company_id,
            "username": "legacy-owner",
            "email": _LEGACY_USER_EMAIL,
            "hashed_password": _LEGACY_USER_HASH,
        },
    )
    return user_id


def upgrade() -> None:
    bind = op.get_bind()

    tenant_tables = (
        "users",
        "units",
        "documents",
        "drafts",
        "chat_sessions",
        "chat_messages",
        "invited_emails",
    )
    if not any(_any_unassigned(bind, table) for table in tenant_tables):
        return

    legacy_company_id = _get_or_create_legacy_company(bind)

    # users.company_id stays NULL for role='root' (see 0011's CHECK
    # constraint) -- no pre-existing row can be root today (the role didn't
    # exist before this migration), but this stays correct if that ever
    # changes.
    bind.execute(
        text(
            "UPDATE users SET company_id = :cid WHERE company_id IS NULL AND role != 'root'"
        ),
        {"cid": legacy_company_id},
    )
    bind.execute(
        text("UPDATE units SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )
    bind.execute(
        text("UPDATE invited_emails SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )
    # Best-effort, not required for 0011 (their NOT NULL enforcement is
    # deferred to Faz 3 -- see this module's docstring).
    bind.execute(
        text("UPDATE drafts SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )
    bind.execute(
        text("UPDATE chat_sessions SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )
    bind.execute(
        text(
            "UPDATE chat_messages cm SET company_id = :cid "
            "FROM chat_sessions cs WHERE cm.session_id = cs.id AND cm.company_id IS NULL"
        ),
        {"cid": legacy_company_id},
    )

    # documents needs both company_id and a real owner_id (owner_id becomes
    # NOT NULL with an FK in 0011) -- a pre-tenancy ownerless document had
    # no owner at all under the old REQUIRE_AUTH=False demo mode.
    if _any_unassigned(bind, "documents"):
        legacy_owner_id = _get_or_create_legacy_owner(bind, legacy_company_id)
        bind.execute(
            text(
                "UPDATE documents SET company_id = :cid, "
                "owner_id = COALESCE(owner_id, :oid) WHERE company_id IS NULL"
            ),
            {"cid": legacy_company_id, "oid": legacy_owner_id},
        )


def downgrade() -> None:
    # Data-only migration -- nothing to structurally undo. The legacy
    # company/user rows are left in place rather than deleted, since 0009's
    # downgrade drops the columns that reference them anyway and deleting
    # here would risk racing that.
    pass
