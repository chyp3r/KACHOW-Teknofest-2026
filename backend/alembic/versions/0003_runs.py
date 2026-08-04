"""Add runs and run_steps: the audit trail of what the planning graph decided.

Mirrors app.observability.model.run_model.RunModel/RunStepModel. Before this,
a run's decision trail existed only as a log line and Prometheus aggregates
(app.observability.ai_metrics) -- "what did the system decide on this
specific request, and why" was unanswerable after the fact. runs captures
the resolved PlanDecision (intent/source/confidence/evidence/alternatives);
run_steps captures each plan step's status and duration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("thread_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("input_text", sa.String(), nullable=False, server_default=""),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("plan_steps", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("alternatives", sa.JSON(), nullable=False),
        sa.Column("clarification", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
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
    op.create_index("ix_runs_id", "runs", ["id"])
    op.create_index("ix_runs_thread_id", "runs", ["thread_id"])
    op.create_index("ix_runs_user_id", "runs", ["user_id"])

    op.create_table(
        "run_steps",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(), nullable=True),
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
    op.create_index("ix_run_steps_id", "run_steps", ["id"])
    op.create_index("ix_run_steps_run_id", "run_steps", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_steps_run_id", table_name="run_steps")
    op.drop_index("ix_run_steps_id", table_name="run_steps")
    op.drop_table("run_steps")

    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_index("ix_runs_thread_id", table_name="runs")
    op.drop_index("ix_runs_id", table_name="runs")
    op.drop_table("runs")
