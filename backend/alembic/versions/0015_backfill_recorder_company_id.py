"""Backfill company_id on drafts/chat_sessions/chat_messages/runs/run_steps/guardrail_events.

Faz 1 added `company_id` to these six tables but left it nullable: they are
written from deep inside the LangGraph orchestration layer
(`app.observability.run_recorder`, `app.observability.guardrail_recorder`,
`app.domains.drafts.draft_recorder`, `app.domains.chat.chat_recorder`),
which did not carry `company_id` through `PlanningState` until this Faz 4
PR threaded it through alongside `user_id`. This migration is the same
three-stage pattern `0009_companies`/`0010_backfill_tenancy`/
`0011_tenancy_constraints` established for the first tenancy retrofit: pure
data here (backfill), `NOT NULL` + RLS in `0016_recorder_tables_rls` --
splitting them means a partially-backfilled database fails loudly at 0016,
not silently here.

Idempotent and restartable, same convention as `0010_backfill_tenancy`:
every `UPDATE` is scoped to `WHERE company_id IS NULL`, and reuses that
same migration's "legacy-pre-tenancy" company (by slug) rather than
creating a second one, so a database already backfilled by 0010 attributes
these rows to the identical fallback tenant.

Backfill sources, in priority order (most reliable first):

- `chat_sessions`, `drafts`, `runs`: from `user_id`'s own `company_id`, when
  `user_id` is set and resolves to a real user; the legacy company
  otherwise (a userless historical row from the pre-auth demo path).
- `chat_messages`: denormalized from its parent `chat_sessions.company_id`
  via `session_id`.
- `run_steps`: denormalized from its parent `runs.company_id` via `run_id`.
- `guardrail_events`: from its `run_id`'s `runs.company_id` first (most
  specific -- a decision made *during* a specific run belongs to that run's
  company beyond doubt), falling back to `requester_user_id`'s
  `company_id`, then the legacy company.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_COMPANY_SLUG = "legacy-pre-tenancy"


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

    from uuid import uuid4

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


def upgrade() -> None:
    bind = op.get_bind()

    tables = ("drafts", "chat_sessions", "chat_messages", "runs", "run_steps", "guardrail_events")
    if not any(_any_unassigned(bind, table) for table in tables):
        return

    legacy_company_id = _get_or_create_legacy_company(bind)

    # ------------------------------------------------------------------
    # Tables with their own user_id: resolve via the user's own company,
    # falling back to the legacy company for a userless/unresolvable row.
    # ------------------------------------------------------------------
    for table in ("chat_sessions", "drafts", "runs"):
        bind.execute(
            text(
                f"""
                UPDATE {table} t SET company_id = u.company_id
                FROM users u
                WHERE t.user_id = u.id AND t.company_id IS NULL AND u.company_id IS NOT NULL
                """
            )
        )
        bind.execute(
            text(f"UPDATE {table} SET company_id = :cid WHERE company_id IS NULL"),
            {"cid": legacy_company_id},
        )

    # ------------------------------------------------------------------
    # Denormalized from their parent row.
    # ------------------------------------------------------------------
    bind.execute(
        text(
            """
            UPDATE chat_messages cm SET company_id = cs.company_id
            FROM chat_sessions cs
            WHERE cm.session_id = cs.id AND cm.company_id IS NULL
            """
        )
    )
    bind.execute(
        text("UPDATE chat_messages SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )

    bind.execute(
        text(
            """
            UPDATE run_steps rs SET company_id = r.company_id
            FROM runs r
            WHERE rs.run_id = r.id AND rs.company_id IS NULL
            """
        )
    )
    bind.execute(
        text("UPDATE run_steps SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )

    # guardrail_events: run_id's company first (most specific), then
    # requester_user_id's, then the legacy company.
    bind.execute(
        text(
            """
            UPDATE guardrail_events ge SET company_id = r.company_id
            FROM runs r
            WHERE ge.run_id = r.id AND ge.company_id IS NULL
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE guardrail_events ge SET company_id = u.company_id
            FROM users u
            WHERE ge.requester_user_id = u.id AND ge.company_id IS NULL AND u.company_id IS NOT NULL
            """
        )
    )
    bind.execute(
        text("UPDATE guardrail_events SET company_id = :cid WHERE company_id IS NULL"),
        {"cid": legacy_company_id},
    )


def downgrade() -> None:
    # Data-only migration -- nothing to structurally undo. Same call
    # 0010_backfill_tenancy makes for its own legacy-company backfill: the
    # rows are left as-is rather than reset to NULL, since 0016's downgrade
    # (dropping the NOT NULL constraint) doesn't require it either.
    pass
