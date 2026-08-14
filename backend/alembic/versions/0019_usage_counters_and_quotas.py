"""Add usage_counters, company_quotas -- Faz 6.

Mirrors app.domains.quotas.model.{usage_counter_model,company_quota_model}.
Same shape as 0014/0017: brand new tables, company_id NOT NULL from
creation, RLS enabled in the same migration.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("usage_counters", "company_quotas")


def _enable_rls(table: str) -> None:
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


def upgrade() -> None:
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("period", sa.String(), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_usage_counters_company_id_companies"),
        sa.UniqueConstraint("company_id", "metric", "period", name="uq_usage_counters_company_metric_period"),
    )
    op.create_index("ix_usage_counters_id", "usage_counters", ["id"])
    op.create_index("ix_usage_counters_company_id", "usage_counters", ["company_id"])

    op.create_table(
        "company_quotas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("max_documents_per_month", sa.Integer(), nullable=True),
        sa.Column("max_drafts_per_month", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_company_quotas_company_id_companies"),
        sa.UniqueConstraint("company_id", name="uq_company_quotas_company_id"),
    )
    op.create_index("ix_company_quotas_id", "company_quotas", ["id"])
    op.create_index("ix_company_quotas_company_id", "company_quotas", ["company_id"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("company_quotas")
    op.drop_table("usage_counters")
