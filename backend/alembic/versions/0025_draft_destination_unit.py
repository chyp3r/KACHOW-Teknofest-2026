"""Add drafts.destination_unit_id, drafts.destination_justification -- Faz 3 (#199).

`drafts.destination` has always been the routing graph's chosen unit
*name* (free text, see DraftModel's own docstring) -- every consumer that
needed an actual `units` row (DraftShareService.send, previously) had to
re-resolve it by name at read time. This migration makes that resolution a
column instead: backfilled once here, and populated going forward by
app.domains.drafts.draft_recorder.record_draft (both the direct-API and
chat call sites already funnel through it).

`destination_justification` persists RouteOutput.justification, which the
routing graph already produces but nothing ever stored -- needed so a
transfer confirmation (Faz 4) can show "why this unit" without re-running
routing.

Nullable, not backfilled to a sentinel: an unresolved unit name (renamed/
deleted since, or the routing graph came back empty) is an honest NULL,
same convention `draft_shares.suggested_unit_id` already established.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("destination_unit_id", sa.String(), nullable=True))
    op.add_column("drafts", sa.Column("destination_justification", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_drafts_destination_unit_id_units", "drafts", "units", ["destination_unit_id"], ["id"]
    )
    op.create_index("ix_drafts_destination_unit_id", "drafts", ["destination_unit_id"])

    # One-time backfill: resolve every existing draft's free-text
    # `destination` against `units` within its own company. A name that no
    # longer matches any unit (renamed, deleted, or routing came back
    # empty) is left NULL -- not an error, an honest "unresolved".
    op.execute(
        """
        UPDATE drafts d
        SET destination_unit_id = u.id
        FROM units u
        WHERE u.company_id = d.company_id
          AND u.name = d.destination
          AND d.destination IS NOT NULL
          AND d.destination != ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_drafts_destination_unit_id", table_name="drafts")
    op.drop_constraint("fk_drafts_destination_unit_id_units", "drafts", type_="foreignkey")
    op.drop_column("drafts", "destination_justification")
    op.drop_column("drafts", "destination_unit_id")
