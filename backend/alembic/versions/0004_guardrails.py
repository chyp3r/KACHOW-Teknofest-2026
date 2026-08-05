"""Add guardrail_events and sensitivity/PII columns on documents.

Mirrors app.observability.model.guardrail_model.GuardrailEventModel and the
new columns on app.domains.documents.model.document_model.DocumentModel.
guardrail_events is the audit trail for input/output guardrail decisions
(PII/sensitivity findings, groundedness/leakage gate verdicts) -- the same
"always-on, first-party record, independent of the optional Langfuse tracer"
role RunModel/RunStepModel (0003) already fill for planning-graph runs.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "sensitivity_level", sa.String(), nullable=False, server_default="unmarked"
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "pii_flagged", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )

    op.create_table(
        "guardrail_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("requester_user_id", sa.String(), nullable=True),
        sa.Column("requester_role", sa.String(), nullable=True),
        sa.Column("effective_clearance", sa.String(), nullable=True),
        sa.Column("related_document_ids", sa.JSON(), nullable=False),
        sa.Column("llm_model_version", sa.String(), nullable=True),
        sa.Column("prompt_template_version", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
    )
    op.create_index("ix_guardrail_events_id", "guardrail_events", ["id"])
    op.create_index("ix_guardrail_events_run_id", "guardrail_events", ["run_id"])
    op.create_index("ix_guardrail_events_document_id", "guardrail_events", ["document_id"])
    op.create_index("ix_guardrail_events_stage", "guardrail_events", ["stage"])
    op.create_index("ix_guardrail_events_kind", "guardrail_events", ["kind"])
    op.create_index("ix_guardrail_events_decision", "guardrail_events", ["decision"])
    op.create_index(
        "ix_guardrail_events_requester_user_id", "guardrail_events", ["requester_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_guardrail_events_requester_user_id", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_decision", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_kind", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_stage", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_document_id", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_run_id", table_name="guardrail_events")
    op.drop_index("ix_guardrail_events_id", table_name="guardrail_events")
    op.drop_table("guardrail_events")

    op.drop_column("documents", "pii_flagged")
    op.drop_column("documents", "sensitivity_level")
