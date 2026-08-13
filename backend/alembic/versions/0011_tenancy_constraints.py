"""Enforce the tenancy boundary: NOT NULL + constraints, now that 0010 backfilled every row.

Split from `0009_companies`/`0010_backfill_tenancy` on purpose (see both
modules' docstrings): this is the migration that fails loudly if the
backfill was incomplete, rather than the schema change silently accepting
NULLs forever. If this migration raises a NOT NULL violation, `0010` did not
finish -- re-run it, don't weaken this one.

Mirrors the ORM models exactly as of this revision:
- `users.company_id`: NOT NULL unless role='root' (root has no company --
  see `UserModel`'s docstring), enforced by a CHECK constraint rather than
  convention alone.
- `units.company_id`: NOT NULL. `units.name` stops being globally unique
  (`uq_units_name`, dropped in 0009) in favour of `(company_id, name)`
  (`uq_units_company_name`) -- two companies may both define an "İnsan
  Kaynakları" unit.
- `documents.company_id` and `documents.owner_id`: both NOT NULL, and
  `owner_id` gains a foreign key to `users.id` it never had before
  (REQUIRE_AUTH could previously be off, leaving genuinely ownerless rows;
  auth is mandatory now -- see `settings.REQUIRE_AUTH`'s docstring).
- `invited_emails.company_id`: NOT NULL.

`drafts`, `chat_sessions`, `chat_messages`, `runs`, `run_steps`,
`guardrail_events` are deliberately NOT touched here -- their `company_id`
stays nullable until the recorder call chains that write them carry it
through (Faz 3; see `RunModel.company_id`'s docstring for the full
reasoning). Constraining them now would break every chat turn, draft
generation and run recording the moment this migration lands.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "company_id", existing_type=sa.String(), nullable=True)
    op.create_check_constraint(
        "ck_users_company_id_required_unless_root",
        "users",
        "company_id IS NOT NULL OR role = 'root'",
    )

    op.alter_column("units", "company_id", existing_type=sa.String(), nullable=False)
    op.create_unique_constraint("uq_units_company_name", "units", ["company_id", "name"])

    op.alter_column("documents", "company_id", existing_type=sa.String(), nullable=False)
    op.alter_column("documents", "owner_id", existing_type=sa.String(), nullable=False)
    op.create_foreign_key(
        "fk_documents_owner_id_users", "documents", "users", ["owner_id"], ["id"]
    )

    op.alter_column("invited_emails", "company_id", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    op.alter_column("invited_emails", "company_id", existing_type=sa.String(), nullable=True)

    op.drop_constraint("fk_documents_owner_id_users", "documents", type_="foreignkey")
    op.alter_column("documents", "owner_id", existing_type=sa.String(), nullable=True)
    op.alter_column("documents", "company_id", existing_type=sa.String(), nullable=True)

    op.drop_constraint("uq_units_company_name", "units", type_="unique")
    op.alter_column("units", "company_id", existing_type=sa.String(), nullable=True)

    op.drop_constraint("ck_users_company_id_required_unless_root", "users", type_="check")
