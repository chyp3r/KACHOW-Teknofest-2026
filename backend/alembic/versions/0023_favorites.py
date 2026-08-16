"""Add user_favorites -- Faz 1 (#194).

Mirrors app.domains.users.model.user_favorite_model.UserFavoriteModel. Same
shape as 0022: a brand new table, company_id NOT NULL from creation, RLS
enabled in the same migration.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("user_favorites",)


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
        "user_favorites",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.String(), nullable=False),
        sa.Column("favorite_user_id", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_user_favorites_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name="fk_user_favorites_owner_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["favorite_user_id"], ["users.id"], name="fk_user_favorites_favorite_user_id_users"
        ),
        sa.UniqueConstraint(
            "owner_user_id", "favorite_user_id", name="uq_user_favorites_owner_favorite"
        ),
    )
    op.create_index("ix_user_favorites_id", "user_favorites", ["id"])
    op.create_index("ix_user_favorites_company_id", "user_favorites", ["company_id"])
    op.create_index("ix_user_favorites_owner_user_id", "user_favorites", ["owner_user_id"])
    op.create_index("ix_user_favorites_favorite_user_id", "user_favorites", ["favorite_user_id"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("user_favorites")
