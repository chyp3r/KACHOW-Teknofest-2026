"""Deterministic name -> user resolution for artifact transfers.

Not called by anything in this phase (Faz 3, #199) -- manual sends
(`POST /transfers/send`) already carry an explicit `recipient_id`, resolved
by the caller through `UserSearchDrawer`/`PersonPickerBody` (Faz 2). This
service exists and is fully tested now so the Faz 4 AI channel's
`transfer_resolve` node has a deterministic, already-proven service to call
instead of asking the LLM to guess a name -> user match itself (see the
plan's §2.2/§2.4: "İsim eşleşmesini LLM üzerinden tahmin etme").
"""

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

from app.domains.users.repository import UserFavoriteRepository, UserRepository


@dataclass(frozen=True)
class RecipientCandidate:
    user_id: str
    username: str
    email: str
    unit_name: Optional[str]
    is_favorite: bool


@dataclass(frozen=True)
class RecipientResolution:
    """The outcome of resolving one free-text name within one company.

    Attributes:
        status: `"resolved"` (exactly one candidate), `"ambiguous"`
            (more than one -- the caller must ask the user to disambiguate,
            never guess), or `"not_found"`.
        candidates: Empty for `"not_found"`, exactly one for `"resolved"`,
            two or more for `"ambiguous"` -- favorites ranked first, then
            alphabetically by username.
    """

    status: Literal["resolved", "ambiguous", "not_found"]
    candidates: Tuple[RecipientCandidate, ...]


class RecipientResolutionService:
    def __init__(self, user_repository: UserRepository, favorite_repository: UserFavoriteRepository):
        self.user_repository = user_repository
        self.favorite_repository = favorite_repository

    async def resolve(self, *, name: str, company_id: str, requester_id: str) -> RecipientResolution:
        """Resolve `name` to a company user.

        An exact (case-insensitive) `username` match wins outright over a
        broader substring search -- if someone types the recipient's full
        username, that is never treated as ambiguous just because a
        substring search would also surface unrelated partial matches.
        Falling back to substring search only when no exact match exists
        keeps "Ahmet" correctly ambiguous between two different Ahmets
        while "ahmet.yilmaz" resolves directly to the one account with
        that exact username.
        """
        name = name.strip()
        if not name:
            return RecipientResolution(status="not_found", candidates=())

        exact_matches, _ = await self._search(company_id, requester_id, q=name)
        normalized = name.casefold()
        exact = [c for c in exact_matches if c.username.casefold() == normalized]
        candidates = exact if exact else exact_matches

        if not candidates:
            return RecipientResolution(status="not_found", candidates=())
        if len(candidates) == 1:
            return RecipientResolution(status="resolved", candidates=tuple(candidates))
        return RecipientResolution(status="ambiguous", candidates=tuple(candidates))

    async def _search(
        self, company_id: str, requester_id: str, *, q: str
    ) -> Tuple[list[RecipientCandidate], int]:
        results = await self.user_repository.search(company_id, q=q, skip=0, limit=20)
        candidates = []
        for user, unit_name in results:
            is_favorite = await self.favorite_repository.is_favorite(requester_id, user.id, company_id)
            candidates.append(
                RecipientCandidate(
                    user_id=user.id,
                    username=user.username,
                    email=user.email,
                    unit_name=unit_name,
                    is_favorite=is_favorite,
                )
            )
        candidates.sort(key=lambda c: (not c.is_favorite, c.username.casefold()))
        return candidates, len(candidates)
