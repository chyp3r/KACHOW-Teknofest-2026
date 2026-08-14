"""Add audit_log -- Faz 6.

Mirrors app.domains.audit.model.audit_log_model.AuditLogModel. New table,
`company_id` nullable from creation (the one deliberate exception among this
codebase's tenant tables -- see the model's own docstring for why a ROOT
subject's system-wide actions have no single company to attach to), so no
backfill step either.

The RLS policy is the *same* `tenant_isolation` shape every other table
uses, unmodified: `company_id = current_setting(...) OR is_root`. A `NULL`
`company_id` makes the first half of that OR evaluate to `NULL` (not `TRUE`)
under Postgres's three-valued logic, so a system-wide row is only ever
visible through the `is_root` branch -- exactly the intended behaviour,
requiring no special-casing in the policy itself.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.String(), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=True),
        sa.Column("acting_as_company_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("decision", sa.String(), nullable=False, server_default="permit"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(), nullable=True),
        sa.Column("correlation_id", sa.String(), nullable=True),
        sa.Column("prev_hash", sa.String(), nullable=False),
        sa.Column("hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_audit_log_company_id_companies"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_log_actor_user_id_users"),
        sa.UniqueConstraint("company_id", "seq", name="uq_audit_log_company_seq"),
    )
    op.create_index("ix_audit_log_id", "audit_log", ["id"])
    op.create_index("ix_audit_log_company_id", "audit_log", ["company_id"])
    op.create_index("ix_audit_log_actor_user_id", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_hash", "audit_log", ["hash"])
    op.create_index("ix_audit_log_correlation_id", "audit_log", ["correlation_id"])

    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_log
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
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log;")
    op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY;")
    op.drop_table("audit_log")
