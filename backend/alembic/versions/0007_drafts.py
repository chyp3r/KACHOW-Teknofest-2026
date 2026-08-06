"""Add drafts: an append-only version chain for generated/revised drafts.

Mirrors app.domains.drafts.model.draft_model.DraftModel. Before this,
`documents.draft_service.DraftService.generate_draft_and_route` was fully
stateless -- it returned a DraftResponseSchema (draft_id always "") without
saving anything, and a chat-produced draft only ever existed inside the
LangGraph checkpointer's HITL state. Each row here is one version; a
revision never overwrites its parent, it appends a new row chained via
parent_draft_id, so `session_id` + `version` reconstructs the full edit
history.

This was developed on a branch independent of 0006
(chat_sessions/chat_messages) with no dependency between them, originally
chained onto 0005 as a sibling head to 0006. Rebased onto 0006 as a normal
linear step once 0006 landed on main first, avoiding the two-heads/merge-
revision situation entirely.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "drafts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_draft_id", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("correspondence_type", sa.String(), nullable=True),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=True),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("judge", sa.JSON(), nullable=True),
        sa.Column("missing_information", sa.JSON(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_draft_id"], ["drafts.id"]),
    )
    op.create_index("ix_drafts_id", "drafts", ["id"])
    op.create_index("ix_drafts_user_id", "drafts", ["user_id"])
    op.create_index("ix_drafts_session_id", "drafts", ["session_id"])
    op.create_index("ix_drafts_document_id", "drafts", ["document_id"])
    op.create_index("ix_drafts_parent_draft_id", "drafts", ["parent_draft_id"])


def downgrade() -> None:
    op.drop_index("ix_drafts_parent_draft_id", table_name="drafts")
    op.drop_index("ix_drafts_document_id", table_name="drafts")
    op.drop_index("ix_drafts_session_id", table_name="drafts")
    op.drop_index("ix_drafts_user_id", table_name="drafts")
    op.drop_index("ix_drafts_id", table_name="drafts")
    op.drop_table("drafts")
