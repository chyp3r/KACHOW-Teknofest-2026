"""Deterministic, DB-backed "which artifact does 'gönder' refer to" resolution.

The AI channel's `propose_transfer` tool (`app.ai.tools.transfer_tools`,
called by the assist step's own model) needs to answer "which draft" (or
"which document") a message like "son taslağı Ahmet'e gönder" refers to --
without relying on `SessionFocus.active_draft`, which is turn-scoped and
self-clears after `ACTIVE_DRAFT_IDLE_LIMIT` idle turns (see
`app.ai.session.focus`'s own docstring). A user who drafts, does several
turns of unrelated work, and only later asks to send it must still resolve
correctly -- this module is what makes that true, by going to the database
instead of the in-memory focus channel.

Ladder (plan §C2), draft and document each running the same three tiers:

1. An explicit reference already resolved by the caller (a real `drafts.id`/
   document storage path -- never guessed from free text here; that would
   just move the guessing into a different function).
2. The thread's own most recent draft/document -- survives any number of
   idle turns, since it is a plain `updated_at`/`created_at` query with no
   idle-turn concept at all.
3. The requesting user's own most recent drafts/documents company-wide, when
   the thread has none -- covers a session that never drafted anything
   itself (the user came from `/drafts` or `/documents` instead).

More than one candidate at any tier is `"ambiguous"`, never resolved by
picking one -- the LLM does not choose here, same as
`RecipientResolutionService`.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Union

from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository

#: How many company-wide candidates tier 3 offers before giving up and
#: asking the user to be more specific instead of rendering an unwieldy list.
DEFAULT_CANDIDATE_LIMIT = 5

Artifact = Union[DraftModel, DocumentModel]


@dataclass(frozen=True)
class ArtifactResolution:
    """The outcome of resolving one artifact reference.

    Attributes:
        status: `"resolved"` (exactly one candidate), `"ambiguous"` (more
            than one -- the caller must disambiguate, never guess), or
            `"unresolved"` (nothing found at any tier).
        artifact_kind: `"draft"` | `"document"`.
        candidates: Empty for `"unresolved"`, exactly one for `"resolved"`,
            two or more for `"ambiguous"`.
    """

    status: Literal["resolved", "ambiguous", "unresolved"]
    artifact_kind: Literal["draft", "document"]
    candidates: tuple


class ArtifactResolutionService:
    def __init__(self, draft_repository: DraftRepository, document_repository: DocumentRepository):
        self.draft_repository = draft_repository
        self.document_repository = document_repository

    async def resolve_draft(
        self,
        *,
        company_id: str,
        user_id: str,
        thread_id: Optional[str],
        explicit_draft_id: Optional[str] = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> ArtifactResolution:
        """Resolve "the draft" the user means, per this module's ladder.

        Args:
            company_id: Tenant scope.
            user_id: The requesting user -- tier 3 only ever looks at
                *their own* drafts, never the company's.
            thread_id: The chat session id (`DraftModel.session_id`'s
                counterpart) -- tier 2's key. `draft_recorder.record_draft`
                writes every chat-produced draft under this same id, so this
                is exactly "what this conversation has produced so far".
            explicit_draft_id: A reference the caller already resolved
                (tier 1), e.g. from `SessionFocus.active_draft_id` when the
                message reads as deictic ("bu taslağı"). `None` skips this
                tier outright.
            candidate_limit: Tier 3's cap.
        """
        if explicit_draft_id:
            draft = await self.draft_repository.get_by_id(explicit_draft_id)
            if draft is not None and draft.company_id == company_id:
                return ArtifactResolution(status="resolved", artifact_kind="draft", candidates=(draft,))

        if thread_id:
            draft = await self.draft_repository.get_latest_for_session(thread_id)
            if draft is not None and draft.company_id == company_id:
                return ArtifactResolution(status="resolved", artifact_kind="draft", candidates=(draft,))

        candidates: Sequence[DraftModel] = await self.draft_repository.list_drafts(
            company_id=company_id, user_id=user_id, limit=candidate_limit
        )
        return _resolution_from_candidates("draft", candidates)

    async def resolve_document(
        self,
        *,
        company_id: str,
        user_id: str,
        explicit_document_id: Optional[str] = None,
        focus_document_id: Optional[str] = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> ArtifactResolution:
        """Resolve "the document" the user means -- same ladder shape, tier 2
        here is `SessionFocus.active_document_id` rather than a session
        query, since documents are not versioned per-session the way drafts
        are.
        """
        for document_id in (explicit_document_id, focus_document_id):
            if not document_id:
                continue
            document = await self.document_repository.get_by_id(document_id, company_id)
            if document is not None:
                return ArtifactResolution(status="resolved", artifact_kind="document", candidates=(document,))

        candidates: Sequence[DocumentModel] = await self.document_repository.list_for_owner(
            company_id, user_id, limit=candidate_limit
        )
        return _resolution_from_candidates("document", candidates)


def _resolution_from_candidates(
    artifact_kind: Literal["draft", "document"], candidates: Sequence[Artifact]
) -> ArtifactResolution:
    if not candidates:
        return ArtifactResolution(status="unresolved", artifact_kind=artifact_kind, candidates=())
    if len(candidates) == 1:
        return ArtifactResolution(status="resolved", artifact_kind=artifact_kind, candidates=tuple(candidates))
    return ArtifactResolution(status="ambiguous", artifact_kind=artifact_kind, candidates=tuple(candidates))
