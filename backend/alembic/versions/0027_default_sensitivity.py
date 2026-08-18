"""Backfill documents.sensitivity_level UNMARKED -> TASNIF_DISI (#214).

A document whose gizlilik_derecesi was never extracted (no confidentiality
stamp on the page at all) used to persist as `sensitivity_level="unmarked"`
-- distinct in the AI layer's own ``SensitivityAssessment`` from a document
positively marked "Tasnif Dışı", but indistinguishable to every downstream
consumer of this column (access-control comparisons, the Qdrant
`sensitivity_rank` retrieval filter, the frontend's "gizlilik derecesi
bulunamadı"-reading badge): they all only ever see the persisted string, so
"never stated" and "no classification at all" read identically as an
apparent gap in the system's own analysis.

`app.ai.guardrails.sensitivity.assess` now resolves this at analysis time --
`SensitivityAssessment.level` keeps the raw UNMARKED fact for the audit
trail, but `effective_level` (what `DocumentService._register_document`
persists here going forward, see `GuardrailPolicy.default_sensitivity_level`)
defaults an absent grade to the lowest positive one, "Tasnif Dışı", the same
way a paper registry would treat an unstamped incoming letter as
unclassified rather than as an error. This migration backfills every row
written before that change.

`unmarked` (rank 0) -> `tasnif_disi` (rank 1) is strictly a widening of
`sensitivity_rank`, never a narrowing: it can only make the Qdrant
retrieval filter (`sensitivity_rank <= requester_clearance.rank`) and
`assert_clearance` *more* restrictive for a row that changes, never less --
every role's clearance floor is `tasnif_disi` or above (see
`GuardrailPolicy.role_clearance_map`), so this backfill cannot revoke access
anyone actually had.

`document_pool_items.metadata_snapshot` (0026) is deliberately left
untouched -- it is a frozen historical record of what a recipient saw at
transfer time, not a live projection of `documents.sensitivity_level`.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

documents = sa.table("documents", sa.column("sensitivity_level", sa.String()))


def upgrade() -> None:
    op.execute(
        documents.update()
        .where(documents.c.sensitivity_level == "unmarked")
        .values(sensitivity_level="tasnif_disi")
    )
    op.alter_column(
        "documents",
        "sensitivity_level",
        server_default="tasnif_disi",
    )


def downgrade() -> None:
    # Intentional no-op: once backfilled, a "tasnif_disi" row no longer
    # records whether it was ever positively marked or was defaulted here --
    # reverting the server_default would not recover that distinction for
    # any row, so there is nothing a downgrade could correctly restore.
    op.alter_column(
        "documents",
        "sensitivity_level",
        server_default="unmarked",
    )
