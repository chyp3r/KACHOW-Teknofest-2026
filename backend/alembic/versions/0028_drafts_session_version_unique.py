"""Add a unique index on drafts (session_id, version) -- C13, Faz 8 (#218).

`DraftRepository.create_version` computes the next version number as
`parent.version + 1` (read the current latest row, add one, insert) with no
database-level guarantee that two concurrent calls against the same
`session_id` can't both read the same `parent` and both insert at the same
version -- a double-click on "resume" or "revise iste" racing the first
request's own in-flight write, most concretely. Nothing before this caught
that: the second insert silently succeeded, leaving two live rows sharing
one `(session_id, version)` pair, and `get_latest_for_session`'s `ORDER BY
version DESC LIMIT 1` picked between them arbitrarily from then on.

The index is partial on two counts, matching how every reader in
`DraftRepository` already treats these two things:

- `WHERE session_id IS NOT NULL`: a direct `POST /documents/draft` call (no
  chat session) leaves `session_id` NULL, and Postgres already treats every
  NULL as distinct for uniqueness purposes -- this predicate exists to
  document that deliberately, not to work around anything.
- `AND NOT is_deleted`: soft-deleted rows are already invisible to every
  version-chain query in this file (`get_latest_for_session`,
  `list_versions_for_session`, `_latest_version_query` all filter
  `is_deleted.is_(False)`) -- the constraint should hold over exactly the
  same set of rows the application logic treats as "real".

This is a database-level backstop, not a fix for the race itself: the
in-process half (a per-session lock serializing concurrent chat turns
against the same thread_id) lives in `app.domains.chat.chat_service`. A
losing concurrent writer now gets a loud `IntegrityError` instead of a
silent duplicate -- correct, if not yet a graceful retry.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX ix_drafts_session_version_unique
        ON drafts (session_id, version)
        WHERE session_id IS NOT NULL AND NOT is_deleted
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_drafts_session_version_unique")
