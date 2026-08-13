"""Add companies: the multi-tenancy root, and a nullable company_id on every tenant table.

Mirrors app.domains.companies.model.company_model.CompanyModel. Before this,
the system had no tenant concept at all -- one install, one shared pool of
users/documents/drafts/units, with ADMIN/MANAGER able to see every row in the
database regardless of which "company" (a concept that didn't exist) they
belonged to.

This migration only adds schema, deliberately nullable everywhere: it must
run cleanly against a database that already has rows with no company to
attribute them to. `0010_backfill_tenancy` assigns those rows to a company
(and does so leaving them re-runnable/idempotent), and `0011_tenancy_
constraints` is what actually enforces NOT NULL -- splitting the three apart
means a partially-backfilled database fails loudly at `0011`, not silently
at `0009`.

No demo-company row is inserted here, on purpose: unlike the legacy-data
backfill (0010, which creates its own placeholder company when it finds rows
to attach), the jury-facing demo company is created by
`app.domains.companies.seeder.seed_demo_company` at application boot, the
same idempotent, app-level seeding convention `0008_units.py` already
established for units.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("tax_number", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(), nullable=True),
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
        sa.UniqueConstraint("slug", name="uq_companies_slug"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_companies_created_by_users"),
    )
    op.create_index("ix_companies_id", "companies", ["id"])
    op.create_index("ix_companies_slug", "companies", ["slug"])

    # ------------------------------------------------------------------
    # Nullable company_id everywhere -- see this module's docstring for why
    # NOT NULL waits until 0011.
    # ------------------------------------------------------------------
    _add_company_id("users")
    _add_company_id("units")
    _add_company_id("documents")
    _add_company_id("drafts")
    _add_company_id("chat_sessions")
    _add_company_id("chat_messages")
    _add_company_id("runs")
    _add_company_id("run_steps")
    _add_company_id("guardrail_events")
    _add_company_id("invited_emails")

    # units.name was globally unique; two companies both having "İnsan
    # Kaynakları" must not conflict. The company-scoped replacement
    # (uq_units_company_name) is added in 0011, once company_id is NOT NULL
    # -- a unique constraint over a nullable column would let every NULL
    # through anyway, so there is nothing to gain by adding it early.
    op.drop_constraint("uq_units_name", "units", type_="unique")


def _add_company_id(table: str) -> None:
    op.add_column(table, sa.Column("company_id", sa.String(), nullable=True))
    op.create_index(f"ix_{table}_company_id", table, ["company_id"])
    op.create_foreign_key(
        f"fk_{table}_company_id_companies",
        table,
        "companies",
        ["company_id"],
        ["id"],
    )


def _drop_company_id(table: str) -> None:
    op.drop_constraint(f"fk_{table}_company_id_companies", table, type_="foreignkey")
    op.drop_index(f"ix_{table}_company_id", table_name=table)
    op.drop_column(table, "company_id")


def downgrade() -> None:
    op.create_unique_constraint("uq_units_name", "units", ["name"])

    for table in (
        "invited_emails",
        "guardrail_events",
        "run_steps",
        "runs",
        "chat_messages",
        "chat_sessions",
        "drafts",
        "documents",
        "units",
        "users",
    ):
        _drop_company_id(table)

    op.drop_index("ix_companies_slug", table_name="companies")
    op.drop_index("ix_companies_id", table_name="companies")
    op.drop_table("companies")
