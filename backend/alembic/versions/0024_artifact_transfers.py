"""Add artifact_transfers, artifact_transfer_intents -- Faz 3 (#199).

Mirrors app.domains.transfers.model.{transfer_model,transfer_intent_model}.
Same shape as 0022/0023: brand new tables, company_id NOT NULL from
creation, RLS enabled in the same migration.

conversation_messages.artifact_transfer_id was created as a plain nullable
String by 0022 (artifact_transfers didn't exist yet at that point in the
chain) -- the real FK is added here, now that the target table exists.

artifact_transfer_intents is created now (so its RLS/table-shape ships with
the rest of this migration set) but has no reader/writer yet -- the AI
channel's confirmation state machine that owns it is Faz 4 (#199's plan,
§L). An unused table with enforced RLS is a safe thing to sit on; an
unmigrated one waiting for a future PR is not.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RLS_TABLES = ("artifact_transfers", "artifact_transfer_intents")


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
        "artifact_transfers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("source_artifact_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("snapshot_ref", sa.String(), nullable=True),
        sa.Column("sender_id", sa.String(), nullable=False),
        sa.Column("recipient_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("ai_suggested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recommendation_source", sa.String(), nullable=True),
        sa.Column("recommendation_confidence", sa.Float(), nullable=True),
        sa.Column("cross_unit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_by_user", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("policy_decision", sa.String(), nullable=False),
        sa.Column("policy_reason", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_artifact_transfers_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["sender_id"], ["users.id"], name="fk_artifact_transfers_sender_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["users.id"], name="fk_artifact_transfers_recipient_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name="fk_artifact_transfers_conversation_id_conversations"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation_messages.id"], name="fk_artifact_transfers_message_id_conversation_messages"
        ),
    )
    op.create_index("ix_artifact_transfers_id", "artifact_transfers", ["id"])
    op.create_index("ix_artifact_transfers_company_id", "artifact_transfers", ["company_id"])
    op.create_index("ix_artifact_transfers_sender_id", "artifact_transfers", ["sender_id"])
    op.create_index("ix_artifact_transfers_recipient_id", "artifact_transfers", ["recipient_id"])
    op.create_index("ix_artifact_transfers_source_artifact_id", "artifact_transfers", ["source_artifact_id"])
    # Partial unique index, matching ArtifactTransferModel's own
    # `Index(..., postgresql_where=...)` declaration exactly -- built via
    # op.create_index (not a raw op.execute) so `alembic check` doesn't see
    # a DB index the model doesn't know about.
    op.create_index(
        "uq_artifact_transfers_idempotency",
        "artifact_transfers",
        ["company_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "artifact_transfer_intents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("company_id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("source_artifact_id", sa.String(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("resolved_recipient_id", sa.String(), nullable=True),
        sa.Column("candidate_recipients", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=True),
        sa.Column("policy_hash", sa.String(), nullable=True),
        sa.Column("cross_unit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resulting_transfer_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name="fk_artifact_transfer_intents_company_id_companies"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name="fk_artifact_transfer_intents_requested_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_recipient_id"], ["users.id"], name="fk_artifact_transfer_intents_resolved_recipient_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["resulting_transfer_id"], ["artifact_transfers.id"], name="fk_artifact_transfer_intents_resulting_transfer_id"
        ),
    )
    op.create_index("ix_artifact_transfer_intents_id", "artifact_transfer_intents", ["id"])
    op.create_index("ix_artifact_transfer_intents_company_id", "artifact_transfer_intents", ["company_id"])
    op.create_index(
        "ix_artifact_transfer_intents_thread_state", "artifact_transfer_intents", ["thread_id", "state"]
    )

    for table in _RLS_TABLES:
        _enable_rls(table)

    # conversation_messages.artifact_transfer_id was created FK-less by
    # 0022 (this table didn't exist yet) -- add the real FK now.
    op.create_foreign_key(
        "fk_conversation_messages_artifact_transfer_id",
        "conversation_messages",
        "artifact_transfers",
        ["artifact_transfer_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_conversation_messages_artifact_transfer_id",
        "conversation_messages",
        type_="foreignkey",
    )

    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("artifact_transfer_intents")
    op.execute("DROP INDEX IF EXISTS uq_artifact_transfers_idempotency;")
    op.drop_table("artifact_transfers")
