"""Belge transferleri için deterministik isim -> kullanıcı çözümlemesi.

Bu fazda hiçbir yer tarafından çağrılmıyor (Faz 3, #199) -- manuel
gönderimler (`POST /transfers/send`) zaten çağıran tarafından
`UserSearchDrawer`/`PersonPickerBody` (Faz 2) aracılığıyla çözümlenmiş,
açık bir `recipient_id` taşır. Bu servis şimdiden var ve tamamen test
edilmiş durumda, böylece Faz 4 AI kanalının `propose_transfer` aracı
(`app.ai.tools.transfer_tools`), LLM'den bir isim -> kullanıcı eşleşmesini
kendisinin tahmin etmesini istemek yerine deterministik, kanıtlanmış bir
servisi çağırabilir (bkz. planın §2.2/§2.4'ü: "İsim eşleşmesini LLM
üzerinden tahmin etme" -- model her zaman ham ismi bir araç argümanı
olarak sağlar; bunu gerçek bir kullanıcıya dönüştüren şey budur).
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
    """Bir şirket içinde bir serbest metin isminin çözümlenme sonucu.

    Attributes:
        status: `"resolved"` (tam olarak bir aday), `"ambiguous"` (birden
            fazla -- çağıran kullanıcıdan belirsizliği gidermesini
            istemelidir, asla tahmin etmemelidir) ya da `"not_found"`.
        candidates: `"not_found"` için boş, `"resolved"` için tam olarak
            bir, `"ambiguous"` için iki veya daha fazla -- önce favoriler,
            sonra kullanıcı adına göre alfabetik sıralanır.
    """

    status: Literal["resolved", "ambiguous", "not_found"]
    candidates: Tuple[RecipientCandidate, ...]


class RecipientResolutionService:
    def __init__(self, user_repository: UserRepository, favorite_repository: UserFavoriteRepository):
        self.user_repository = user_repository
        self.favorite_repository = favorite_repository

    async def resolve(self, *, name: str, company_id: str, requester_id: str) -> RecipientResolution:
        """`name`'i bir şirket kullanıcısına çözümler.

        Tam (büyük/küçük harf duyarsız) bir `username` eşleşmesi, daha
        geniş bir alt dize aramasına doğrudan üstün gelir -- biri alıcının
        tam kullanıcı adını yazarsa, bir alt dize araması ilgisiz kısmi
        eşleşmeleri de ortaya çıkaracak diye bu asla belirsiz sayılmaz.
        Yalnızca tam eşleşme bulunmadığında alt dize aramasına geri dönmek,
        "Ahmet"in iki farklı Ahmet arasında doğru şekilde belirsiz
        kalmasını sağlarken "ahmet.yilmaz" tam olarak o kullanıcı adına
        sahip tek hesaba doğrudan çözümlenir.
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
