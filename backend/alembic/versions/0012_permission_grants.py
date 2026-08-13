"""Add permission_grants: the ABAC PDP's PAP (Policy Administration Point) store.

Mirrors app.core.authz.model.permission_grant_model.PermissionGrantModel.
Faz 2 of the tenancy plan (#169) -- see app.core.authz's package docstring
for the engine this table feeds. Purely additive: no existing table changes,
so this migration is safe to run against a live database with no downtime
window needed.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "permission_grants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=False),
        sa.Column("resource_selector", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("effect", sa.String(), nullable=False, server_default="permit"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_permission_grants_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["users.id"], name="fk_permission_grants_granted_by_users"
        ),
    )
    op.create_index("ix_permission_grants_id", "permission_grants", ["id"])
    op.create_index("ix_permission_grants_company_id", "permission_grants", ["company_id"])
    op.create_index(
        "ix_permission_grants_subject_lookup",
        "permission_grants",
        ["company_id", "subject_type", "subject_id", "action"],
    )


def downgrade() -> None:
    op.drop_index("ix_permission_grants_subject_lookup", table_name="permission_grants")
    op.drop_index("ix_permission_grants_company_id", table_name="permission_grants")
    op.drop_index("ix_permission_grants_id", table_name="permission_grants")
    op.drop_table("permission_grants")
