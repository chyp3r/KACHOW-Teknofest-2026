"""Deterministik "bu taslak kime gitmeli" -- yeni bir AI çağrısı yok.

`GET /units/{id}/suggested-recipients`'in zaten olduğu aynı karar
vermeyen (non-decision) yapı (bkz. kendi docstring'i): yönlendirme grafiği
zaten bir birim seçti (`drafts.destination_unit_id`); bu yalnızca o
birimin üyeliğini, önce favoriler olacak şekilde sıralar. Manuel gönderim
arayüzünün (Faz 3), Faz 4 AI kanalının var olmasını beklemeden önerilen
alıcı çipini gösterebilmesi için `GET /transfers/recommendations` olarak
sunulur.
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
    #: "favorite_in_unit" (önce sıralanır) | "unit_member"
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
        """`draft`'ın kendi yönlendirildiği birimin üyelerini, önce favoriler
        olacak şekilde sıralar.

        Önerecek bir şey olmadığında -- asla bir hata değil -- boş bir
        liste döndürür: taslak mevcut değil ya da farklı bir şirkete ait,
        hiçbir zaman bir birime yönlendirilmemiş
        (`destination_unit_id is None`) veya o birim o zamandan beri devre
        dışı bırakılmış. Bir öneri bir ipucudur, bir gereklilik değil;
        boş bir sonuç yalnızca çağıranın manuel aramaya geri döneceği
        anlamına gelir.
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
        # `list_for_unit` zaten primary -> lead -> rest şeklinde sıralar;
        # yalnızca favorileri bunun önüne çıkarmak, sıfırdan yeniden
        # sıralamak yerine geri kalan sırasını korur.
        recommendations.sort(key=lambda r: r.source != "favorite_in_unit")
        return recommendations[:limit]
