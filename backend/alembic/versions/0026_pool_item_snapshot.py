"""Add document_pool_items.metadata_snapshot, transferred_by -- Faz 3 (#199).

`metadata_snapshot` is the copy-on-write half of the evrak transfer model
(see the plan's §D5): the shared blob is never mutated, but `documents`'
metadata row is, so a transferred item freezes that metadata (document_
type, document_type_label, compliance_status, summary, sensitivity_level,
pii_flagged) at transfer time. The recipient reads the snapshot, not the
live `documents` row -- the sender editing fields afterward never changes
what the recipient already saw.

`transferred_by` is `added_by`'s counterpart for the "transfer" source
(see `source`'s own docstring, which already reserved but never used a
`"share"` value for this): the sender, which is not always the same as
whoever technically inserted the row once an AI channel exists (Faz 4).

Both nullable, not backfilled: an existing row with `source="upload"` or
`"manager_push"` was never a transfer, so NULL here means exactly that --
same "no migration for a fact that didn't happen" convention `draft_shares`
already uses.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("document_pool_items", sa.Column("metadata_snapshot", sa.JSON(), nullable=True))
    op.add_column("document_pool_items", sa.Column("transferred_by", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_document_pool_items_transferred_by_users",
        "document_pool_items",
        "users",
        ["transferred_by"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_document_pool_items_transferred_by_users", "document_pool_items", type_="foreignkey"
    )
    op.drop_column("document_pool_items", "transferred_by")
    op.drop_column("document_pool_items", "metadata_snapshot")
