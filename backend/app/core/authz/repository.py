from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.engine import GrantView
from app.core.authz.model.permission_grant_model import PermissionGrantModel
from app.core.enums.user_role import UserRole


def _to_grant_view(row: PermissionGrantModel) -> GrantView:
    """Kalıcı bir satırı ``engine.py``'nin tükettiği DB'den bağımsız biçime dönüştürür."""
    return GrantView(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_selector=row.resource_selector or {},
        effect=row.effect,
        priority=row.priority,
        time_boxed=row.valid_from is not None or row.valid_until is not None,
    )


class PermissionGrantRepository:
    """``permission_grants`` için kalıcılık -- ABAC PDP'nin PAP deposu.

    Her metot açık bir `company_id` alır ve buna göre filtreler, kiracılık
    çalışmasından bu yana diğer her repository ile aynı kural
    (bkz. `app.domains.units.repository.UnitRepository`'nin docstring'i).
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active_for_subject(
        self, company_id: str, role: UserRole, user_id: str, action: str
    ) -> List[GrantView]:
        """Bu özne ve eylemle eşleşen, şu anda etkin her yetkiyi getirir.

        "Etkin" şu anlama gelir: iptal edilmemiş, ve (``valid_from``/
        ``valid_until`` penceresi yok, ya da pencere ``now``'u kapsıyor).
        Ya tam olarak bu ``user_id`` ile ``subject_type="user"`` olan, ya da
        bu ``role`` ile ``subject_type="role"`` olan yetkileri hedefleyen
        yetkilerle eşleşir -- rol tipli bir yetki o rolün her üyesine
        uygulanır, kullanıcı tipli bir yetki ise yalnızca bir kişiye.
        Saklanan bir satırda ``action``'ın kendisi de ``"*"`` olabilir
        (genel bir yetki), bu yüzden bu, ``action`` sütunu gerçek joker
        karakter olan satırlarla da eşleşir.
        """
        now = datetime.now(timezone.utc)
        stmt = select(PermissionGrantModel).where(
            PermissionGrantModel.company_id == company_id,
            PermissionGrantModel.action.in_((action, "*")),
            PermissionGrantModel.revoked_at.is_(None),
            or_(
                PermissionGrantModel.valid_from.is_(None),
                PermissionGrantModel.valid_from <= now,
            ),
            or_(
                PermissionGrantModel.valid_until.is_(None),
                PermissionGrantModel.valid_until >= now,
            ),
            or_(
                and_(
                    PermissionGrantModel.subject_type == "user",
                    PermissionGrantModel.subject_id == user_id,
                ),
                and_(
                    PermissionGrantModel.subject_type == "role",
                    PermissionGrantModel.subject_id == role.value,
                ),
            ),
        )
        result = await self.db.execute(stmt)
        return [_to_grant_view(row) for row in result.scalars().all()]

    async def list_for_user(self, company_id: str, user_id: str) -> List[PermissionGrantModel]:
        """Açıkça ``user_id``'yi hedefleyen, iptal edilmemiş her yetki (rol tipli yetkiler hariç --
        bu, ``GET /users/{id}/permissions`` arayüzü için "bu kişiye özel olarak ne verildi"dir,
        tam etkin yetki kümesi değil)."""
        result = await self.db.execute(
            select(PermissionGrantModel).where(
                PermissionGrantModel.company_id == company_id,
                PermissionGrantModel.subject_type == "user",
                PermissionGrantModel.subject_id == user_id,
                PermissionGrantModel.revoked_at.is_(None),
            ).order_by(PermissionGrantModel.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, grant_id: str, company_id: str) -> Optional[PermissionGrantModel]:
        result = await self.db.execute(
            select(PermissionGrantModel).where(
                PermissionGrantModel.id == grant_id, PermissionGrantModel.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, grant: PermissionGrantModel) -> PermissionGrantModel:
        if not grant.id:
            grant.id = uuid4().hex
        self.db.add(grant)
        await self.db.flush()
        return grant

    async def revoke(self, grant_id: str, company_id: str) -> bool:
        """Bir yetkiyi iptal edilmiş olarak işaretler (silinmez, kendi denetim izi olarak kalır)."""
        grant = await self.get_by_id(grant_id, company_id)
        if grant is None or grant.revoked_at is not None:
            return False
        grant.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True
