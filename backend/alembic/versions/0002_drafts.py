"""Drafts: append-only version history for drafted correspondence.

Mirrors app.domains.drafts.model.draft_model.DraftModel. A conscious
exception to the checkpoint-memory-is-the-only-store principle documented in
app/ai/memory/checkpoint_memory.py: what is persisted here is a workflow
*output* (the drafted text and the metadata around it), not conversation
history -- conversation memory stays entirely in the LangGraph checkpoint,
this table only ever holds a copy of `draft_result.draft` per turn.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_draft_id", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("correspondence_type", sa.String(), nullable=True),
        sa.Column("routed_unit", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_draft_id"], ["drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_drafts_id", "drafts", ["id"])
    op.create_index("ix_drafts_user_id", "drafts", ["user_id"])
    op.create_index("ix_drafts_session_id", "drafts", ["session_id"])
    op.create_index("ix_drafts_document_id", "drafts", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_drafts_document_id", table_name="drafts")
    op.drop_index("ix_drafts_session_id", table_name="drafts")
    op.drop_index("ix_drafts_user_id", table_name="drafts")
    op.drop_index("ix_drafts_id", table_name="drafts")
    op.drop_table("drafts")
