"""Deterministic "who should this draft go to" -- no new AI call.

Same non-decision `GET /units/{id}/suggested-recipients` already is (see
its own docstring): the routing graph already chose a unit
(`drafts.destination_unit_id`); this only ranks that unit's membership,
favorites first. Exposed as `GET /transfers/recommendations` so the manual
send UI (Faz 3) can show a suggested-recipient chip without waiting for
the Faz 4 AI channel to exist.
"""

from dataclasses import dataclass
from typing import List, Literal, Optional

from app.domains.drafts.repository import DraftRepository
from app.domains.units.repository import UnitMembershipRepository, UnitRepository
from app.domains.users.repository import UserFavoriteRepository

DEFAULT_RECOMMENDATION_LIMIT = 5


@dataclass(frozen=True)
class RecipientRecommendation:
    user_id: str
    username: str
    #: "favorite_in_unit" (ranked first) | "unit_member"
    source: Literal["favorite_in_unit", "unit_member"]
    unit_id: str
    unit_name: str


class RecipientRecommendationService:
    def __init__(
        self,
        draft_repository: DraftRepository,
        unit_repository: UnitRepository,
        unit_membership_repository: UnitMembershipRepository,
        favorite_repository: UserFavoriteRepository,
    ):
        self.draft_repository = draft_repository
        self.unit_repository = unit_repository
        self.unit_membership_repository = unit_membership_repository
        self.favorite_repository = favorite_repository

    async def recommend_for_draft(
        self,
        draft_id: str,
        company_id: str,
        requester_id: str,
        limit: int = DEFAULT_RECOMMENDATION_LIMIT,
    ) -> List[RecipientRecommendation]:
        """Rank `draft`'s own routed unit's members, favorites first.

        Returns an empty list -- never an error -- whenever there is
        nothing to recommend: the draft doesn't exist or belongs to a
        different company, it was never routed to a unit
        (`destination_unit_id is None`), or that unit has since been
        deactivated. A recommendation is a hint, not a requirement; an
        empty result just means the caller falls back to manual search.
        """
        draft = await self.draft_repository.get_by_id(draft_id)
        if draft is None or draft.company_id != company_id or draft.is_deleted:
            return []
        return await self._recommend_for_unit(
            draft.destination_unit_id, company_id, requester_id, limit
        )

    async def _recommend_for_unit(
        self, unit_id: Optional[str], company_id: str, requester_id: str, limit: int
    ) -> List[RecipientRecommendation]:
        if not unit_id:
            return []
        unit = await self.unit_repository.get_by_id(unit_id, company_id)
        if unit is None or not unit.is_active:
            return []

        members = await self.unit_membership_repository.list_for_unit(unit.id, company_id)
        favorites = await self.favorite_repository.list_for_owner(requester_id, company_id)
        favorite_ids = {favorite.favorite_user_id for favorite, _user in favorites}

        recommendations = [
            RecipientRecommendation(
                user_id=user.id,
                username=user.username,
                source="favorite_in_unit" if user.id in favorite_ids else "unit_member",
                unit_id=unit.id,
                unit_name=unit.name,
            )
            for _membership, user in members
            if user.id != requester_id
        ]
        # `list_for_unit` already ranks primary -> lead -> rest; only
        # promoting favorites ahead of that keeps the rest of its
        # ordering, rather than re-sorting from scratch.
        recommendations.sort(key=lambda r: r.source != "favorite_in_unit")
        return recommendations[:limit]
