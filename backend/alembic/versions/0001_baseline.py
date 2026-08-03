"""Baseline: users and invited_emails.

Mirrors app.domains.users.model.user_model.UserModel and
app.domains.users.model.invited_email.InvitedEmailModel, which existed with
no migration history at all before this revision -- the auth/users stack was
running against tables Alembic had never created.

Note: this migration does NOT create LangGraph's checkpoint tables
(checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations).
Those are created by AsyncPostgresSaver.setup() at application startup (see
app/infrastructure/checkpointing/postgres.py) and are deliberately excluded
from Alembic's autogenerate via env.py's include_object. Run `alembic upgrade
head` before starting the app; the checkpointer's own setup() is idempotent
and safe to run on every boot.

Revision ID: 0001
Revises:
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="employee"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "invited_emails",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="employee"),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    )
    op.create_index("ix_invited_emails_id", "invited_emails", ["id"])
    op.create_index("ix_invited_emails_email", "invited_emails", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_invited_emails_email", table_name="invited_emails")
    op.drop_index("ix_invited_emails_id", table_name="invited_emails")
    op.drop_table("invited_emails")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
