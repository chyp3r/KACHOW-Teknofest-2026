"""Add unit_memberships, document_pools, document_pool_items -- Faz 4.

Mirrors app.domains.units.model.unit_membership_model.UnitMembershipModel
and app.domains.pools.model.{document_pool_model,document_pool_item_model}.

Unlike the tenancy retrofit migrations (0009-0011), these are brand new
tables with `company_id NOT NULL` from creation -- there are no pre-existing
rows to backfill, so schema, backfill and constraint-enforcement collapse
into one migration instead of three. Row-level security (`ENABLE`+`FORCE
ROW LEVEL SECURITY` + the same `tenant_isolation` policy shape migration
`0013_rls` established) is enabled here too, for the same reason: nothing
to backfill first.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("unit_memberships", "document_pools", "document_pool_items")


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
        "unit_memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("unit_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("role_in_unit", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_unit_memberships_company_id_companies"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], name="fk_unit_memberships_unit_id_units"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_unit_memberships_user_id_users"),
        sa.UniqueConstraint("unit_id", "user_id", name="uq_unit_memberships_unit_user"),
    )
    op.create_index("ix_unit_memberships_id", "unit_memberships", ["id"])
    op.create_index("ix_unit_memberships_company_id", "unit_memberships", ["company_id"])
    op.create_index("ix_unit_memberships_unit_id", "unit_memberships", ["unit_id"])
    op.create_index("ix_unit_memberships_user_id", "unit_memberships", ["user_id"])
    op.create_index(
        "uq_unit_memberships_one_primary_per_user",
        "unit_memberships",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "document_pools",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("owner_type", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_document_pools_company_id_companies"),
    )
    op.create_index("ix_document_pools_id", "document_pools", ["id"])
    op.create_index("ix_document_pools_company_id", "document_pools", ["company_id"])
    op.create_index("ix_document_pools_owner_type", "document_pools", ["owner_type"])
    op.create_index("ix_document_pools_owner_id", "document_pools", ["owner_id"])
    op.create_index(
        "uq_document_pools_one_default_per_owner",
        "document_pools",
        ["owner_type", "owner_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "document_pool_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("added_by", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="upload"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_document_pool_items_company_id_companies"),
        sa.ForeignKeyConstraint(["pool_id"], ["document_pools.id"], name="fk_document_pool_items_pool_id_document_pools"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name="fk_document_pool_items_document_id_documents"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], name="fk_document_pool_items_added_by_users"),
        sa.UniqueConstraint("pool_id", "document_id", name="uq_document_pool_items_pool_document"),
    )
    op.create_index("ix_document_pool_items_id", "document_pool_items", ["id"])
    op.create_index("ix_document_pool_items_company_id", "document_pool_items", ["company_id"])
    op.create_index("ix_document_pool_items_pool_id", "document_pool_items", ["pool_id"])
    op.create_index("ix_document_pool_items_document_id", "document_pool_items", ["document_id"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("document_pool_items")
    op.drop_table("document_pools")
    op.drop_table("unit_memberships")
