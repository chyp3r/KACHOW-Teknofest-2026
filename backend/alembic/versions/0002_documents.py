"""Add documents: the ownership + listing registry for uploaded documents.

Mirrors app.domains.documents.model.document_model.DocumentModel. Before this,
document metadata lived only in uploads_metadata.json on local disk, with no
concept of who uploaded what -- any caller who knew or guessed a storage_path
could read another user's document through chat (see the ai/ architecture
migration's B8 finding). This table is deliberately narrow: it is the
ownership/listing registry, not the document's content -- extracted text and
the full analysis stay in the local JSON cache DocumentService already writes,
which is a separate, larger migration left out of scope here.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("document_type", sa.String(), nullable=False, server_default=""),
        sa.Column("document_type_label", sa.String(), nullable=False, server_default=""),
        sa.Column("compliance_status", sa.String(), nullable=False, server_default=""),
        sa.Column("summary", sa.String(), nullable=False, server_default=""),
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
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_owner_id", "documents", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_owner_id", table_name="documents")
    op.drop_index("ix_documents_id", table_name="documents")
    op.drop_table("documents")
