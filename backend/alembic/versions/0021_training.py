"""Add training_runs, training_samples; company_quotas.max_training_runs_per_month -- Faz C3 (#187).

Mirrors app.domains.training.model.{training_run_model,training_sample_model}.
Same shape as 0019/0020: brand new tables, company_id NOT NULL from
creation, RLS enabled in the same migration. training_runs is created
before training_samples since the latter's training_run_id FKs into it.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("training_runs", "training_samples")


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
        "training_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=False, server_default="manual"),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("artifact_path", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_training_runs_company_id_companies"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], name="fk_training_runs_triggered_by_users"),
    )
    op.create_index("ix_training_runs_id", "training_runs", ["id"])
    op.create_index("ix_training_runs_company_id", "training_runs", ["company_id"])

    op.create_table(
        "training_samples",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("training_run_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_feedback_id", sa.String(), nullable=True),
        sa.Column("source_draft_id", sa.String(), nullable=True),
        sa.Column("prompt_context", sa.Text(), nullable=True),
        sa.Column("chosen", sa.Text(), nullable=True),
        sa.Column("rejected", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("pair_hash", sa.String(), nullable=False),
        sa.Column("used_in_runs", sa.JSON(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_training_samples_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["training_run_id"], ["training_runs.id"], name="fk_training_samples_training_run_id_training_runs"
        ),
        sa.UniqueConstraint("company_id", "pair_hash", name="uq_training_samples_company_pair_hash"),
    )
    op.create_index("ix_training_samples_id", "training_samples", ["id"])
    op.create_index("ix_training_samples_company_id", "training_samples", ["company_id"])
    op.create_index("ix_training_samples_training_run_id", "training_samples", ["training_run_id"])
    op.create_index("ix_training_samples_source", "training_samples", ["source"])
    op.create_index("ix_training_samples_source_feedback_id", "training_samples", ["source_feedback_id"])
    op.create_index("ix_training_samples_source_draft_id", "training_samples", ["source_draft_id"])

    for table in _RLS_TABLES:
        _enable_rls(table)

    op.add_column(
        "company_quotas", sa.Column("max_training_runs_per_month", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("company_quotas", "max_training_runs_per_month")

    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("training_samples")
    op.drop_table("training_runs")
