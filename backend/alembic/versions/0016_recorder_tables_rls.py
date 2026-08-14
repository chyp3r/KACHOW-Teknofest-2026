"""Enforce NOT NULL + Postgres RLS on the six recorder tables backfilled by 0015.

The constraint-enforcement half of the pattern `0009_companies`/
`0010_backfill_tenancy`/`0011_tenancy_constraints` established: this is the
migration that fails loudly if `0015_backfill_recorder_company_id` didn't
finish (a `NOT NULL` violation means re-run 0015, don't weaken this one),
mirroring how `0013_rls` added row-level security once `0011` had already
made `company_id` mandatory on the first batch of tables.

Same `tenant_isolation` policy shape as `0013_rls`/`0014_units_and_pools`:
`company_id = current_setting('app.current_company_id', true) OR
current_setting('app.is_root', true) = 'on'`, `ENABLE`+`FORCE ROW LEVEL
SECURITY` (FORCE matters as much as ENABLE -- see `0013_rls`'s own module
docstring for why).

With this migration, every tenant-shaped table in the system is under RLS.
`companies` itself has no `company_id` column (it *is* the tenant) and
`permission_grants`/`units`/`documents`/`invited_emails`/`users` were
already covered by `0013_rls`/`0014_units_and_pools`.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("drafts", "chat_sessions", "chat_messages", "runs", "run_steps", "guardrail_events")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "company_id", existing_type=sa.String(), nullable=False)

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (
                company_id = current_setting('app.current_company_id', true)
                OR current_setting('app.is_root', true) = 'on'
              )
              WITH CHECK (
                company_id = current_setting('app.current_company_id', true)
                OR current_setting('app.is_root', true) = 'on'
              );
            """
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    for table in reversed(_TABLES):
        op.alter_column(table, "company_id", existing_type=sa.String(), nullable=True)
