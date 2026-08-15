"""Add feedback -- Faz C1 (#183).

Mirrors app.domains.feedback.model.feedback_model.FeedbackModel.

Same shape as 0017_draft_shares_notifications: a brand new table with
`company_id NOT NULL` from creation -- nothing to backfill, so schema and
RLS enforcement collapse into one migration.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("feedback",)


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
        "feedback",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("draft_id", sa.String(), nullable=True),
        sa.Column("target_kind", sa.String(), nullable=False),
        sa.Column("signal", sa.String(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_feedback_company_id_companies"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feedback_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], name="fk_feedback_session_id_chat_sessions"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], name="fk_feedback_message_id_chat_messages"
        ),
        sa.UniqueConstraint(
            "company_id", "user_id", "target_kind", "content_hash", name="uq_feedback_vote_identity"
        ),
    )
    op.create_index("ix_feedback_id", "feedback", ["id"])
    op.create_index("ix_feedback_company_id", "feedback", ["company_id"])
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])
    op.create_index("ix_feedback_session_id", "feedback", ["session_id"])
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"])
    op.create_index("ix_feedback_draft_id", "feedback", ["draft_id"])
    op.create_index("ix_feedback_target_kind", "feedback", ["target_kind"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("feedback")
