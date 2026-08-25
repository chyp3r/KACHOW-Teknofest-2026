from typing import List, Optional

from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository
from app.domains.units.repository import UnitRepository


class DraftService:
    """Business logic for the drafts API.

    Creation happens through `app.domains.drafts.draft_recorder`, called
    from `app.domains.documents.draft_service.DraftService.
    generate_draft_and_route` and from `ChatService` -- both run outside a
    request-scoped session (the latter during SSE streaming), so they own
    their own session/repository instead of going through this service.
    `delete_draft` is the one write this service does own: it runs inside
    the request-scoped session the drafts router already has, with no
    SSE-streaming concern to route around.
    """

    def __init__(self, repository: DraftRepository) -> None:
        self.repository = repository

    async def get_draft(self, draft_id: str) -> DraftModel:
        draft = await self.repository.get_by_id(draft_id)
        if draft is None:
            raise NotFoundException(message="Draft not found.")
        return draft

    async def list_versions(self, draft_id: str) -> List[DraftModel]:
        """Every version in the draft's chain, oldest first.

        Looks the draft up first purely to resolve its `session_id` --
        version chains for a direct-API draft (`session_id=None`) collapse
        to just that one draft, since there is nothing to chain it to.
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            return [draft]
        return await self.repository.list_versions_for_session(draft.session_id)

    async def list_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DraftModel]:
        return await self.repository.list_drafts(
            company_id=company_id,
            session_id=session_id,
            document_id=document_id,
            user_id=user_id,
            skip=skip,
            limit=limit,
        )

    async def count_drafts(
        self,
        company_id: Optional[str] = None,
        session_id: Optional[str] = None,
        document_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        return await self.repository.count_drafts(
            company_id=company_id, session_id=session_id, document_id=document_id, user_id=user_id
        )

    async def delete_draft(self, draft_id: str) -> None:
        """Soft-delete a draft, and the whole version chain it belongs to.

        Raises:
            NotFoundException: If `draft_id` doesn't exist (or is already
                deleted -- `get_by_id` filters `is_deleted`, so a second
                delete call is reported the same as a missing draft rather
                than silently succeeding).
        """
        draft = await self.get_draft(draft_id)
        if draft.session_id is None:
            await self.repository.soft_delete(draft_id)
        else:
            await self.repository.soft_delete_session(draft.session_id)

    async def update_destination(self, draft_id: str, destination: str, company_id: str) -> DraftModel:
        """Override this draft version's routed unit with the caller's own pick.

        The routing graph always proposes a primary + (usually) an
        alternative now (see `app.ai.workflows.routing_graph.
        _best_effort_unit`), but a human may still want a third option --
        this is the write path for that, e.g. from the chat UI's unit
        picker. `destination` need not match a real unit: a custom,
        free-text destination is accepted the same way routing's own
        fallback already tolerates an unmatched name (see
        `DraftModel.destination_unit_id`'s docstring) -- it just resolves
        to no `destination_unit_id`.

        Args:
            draft_id: The specific version being corrected -- not
                necessarily the session's latest (an older version's
                routing can still be corrected after the fact).
            destination: The chosen unit's name, non-empty.
            company_id: The caller's tenant, used to resolve `destination`
                against this company's own `units` (never another
                tenant's).

        Raises:
            NotFoundException: If `draft_id` doesn't exist.
            ValidationException: If `destination` is blank.

        Returns:
            The updated draft row.
        """
        destination = destination.strip()
        if not destination:
            raise ValidationException(message="Birim adı boş olamaz.")
        draft = await self.get_draft(draft_id)
        unit = await UnitRepository(self.repository.db).get_by_name(destination, company_id)
        return await self.repository.update_destination(
            draft,
            destination=destination,
            destination_unit_id=unit.id if unit else None,
            destination_justification="Kullanıcı tarafından manuel olarak seçildi.",
        )

    async def approve_review(self, draft_id: str) -> DraftModel:
        """Mark a draft version's required human review as completed.

        The operation is idempotent so a retried button request cannot create
        a conflicting state. It only resolves the human-approval flag;
        ``missing_information`` remains untouched and continues to appear as
        a separate blocking review item in the client.
        """
        draft = await self.get_draft(draft_id)
        if not draft.requires_human_approval:
            return draft
        return await self.repository.approve_review(draft)
