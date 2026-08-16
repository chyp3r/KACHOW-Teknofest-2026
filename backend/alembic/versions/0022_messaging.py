"""Add conversations, conversation_participants, conversation_messages -- Faz 1 (#194).

Mirrors app.domains.messaging.model.{conversation_model,conversation_participant_model,
conversation_message_model}. Same shape as 0017/0021: brand new tables,
company_id NOT NULL from creation, RLS enabled in the same migration --
nothing to backfill.

conversation_messages.artifact_transfer_id is a plain nullable String here,
not yet a foreign key: artifact_transfers (Faz 3, migration 0024) does not
exist yet, and message ordering/pagination must never depend on the
transfer domain existing. The FK is added by 0024 once both tables do.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("conversations", "conversation_participants", "conversation_messages")


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
        "conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("dm_key", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], name="fk_conversations_company_id_companies"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_conversations_created_by_users"),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])
    op.create_index("ix_conversations_company_id", "conversations", ["company_id"])
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])
    # Partial unique index: at most one kind="dm" conversation per
    # (company_id, dm_key) pair -- a second DM between the same two users is
    # structurally impossible, not merely application-checked. Built via
    # op.create_index (not a raw op.execute) so it matches ConversationModel's
    # own `Index(..., postgresql_where=...)` declaration exactly -- otherwise
    # `alembic check`/autogenerate sees a DB index the model doesn't know
    # about and proposes to drop it on the next migration.
    op.create_index(
        "uq_conversations_dm_key",
        "conversations",
        ["company_id", "dm_key"],
        unique=True,
        postgresql_where=sa.text("kind = 'dm'"),
    )

    op.create_table(
        "conversation_participants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role_in_conversation", sa.String(), nullable=False, server_default="member"),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_read_message_id", sa.String(), nullable=True),
        sa.Column("muted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_conversation_participants_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_participants_conversation_id_conversations",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_conversation_participants_user_id_users"
        ),
        sa.UniqueConstraint(
            "conversation_id", "user_id", name="uq_conversation_participants_conv_user"
        ),
    )
    op.create_index("ix_conversation_participants_id", "conversation_participants", ["id"])
    op.create_index(
        "ix_conversation_participants_company_id", "conversation_participants", ["company_id"]
    )
    op.create_index(
        "ix_conversation_participants_conversation_id", "conversation_participants", ["conversation_id"]
    )
    op.create_index("ix_conversation_participants_user_id", "conversation_participants", ["user_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("sender_id", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default="text"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("artifact_transfer_id", sa.String(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_conversation_messages_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_conversation_messages_conversation_id_conversations",
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name="fk_conversation_messages_sender_id_users"
        ),
    )
    op.create_index("ix_conversation_messages_id", "conversation_messages", ["id"])
    op.create_index("ix_conversation_messages_company_id", "conversation_messages", ["company_id"])
    op.create_index("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"])
    op.create_index(
        "ix_conversation_messages_conv_created",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("conversation_messages")
    op.drop_table("conversation_participants")
    op.execute("DROP INDEX IF EXISTS uq_conversations_dm_key;")
    op.drop_table("conversations")
