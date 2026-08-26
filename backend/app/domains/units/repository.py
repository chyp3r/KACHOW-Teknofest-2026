from typing import List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.users.model.user_model import UserModel


class UnitRepository:
    """Birimler ile ilgili SQLAlchemy veritabanı işlemleri için SOTA Repository.

    Her metot açık bir `company_id` alır ve buna göre filtreler -- aynı
    kural ve gerekçe için `app.domains.documents.repository.
    DocumentRepository`'nin docstring'ine bakınız.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, unit_id: str, company_id: str) -> Optional[UnitModel]:
        """`company_id` kapsamında, birincil anahtar ID'sine göre bir birim getirir."""
        result = await self.db.execute(
            select(UnitModel).where(UnitModel.id == unit_id, UnitModel.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str, company_id: str) -> Optional[UnitModel]:
        """`company_id` içinde ada göre bir birim getirir (benzersizlik şirket başına, global değil)."""
        result = await self.db.execute(
            select(UnitModel).where(UnitModel.name == name, UnitModel.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self, company_id: str) -> List[UnitModel]:
        """`company_id`'nin aktif olsun olmasın her birimini, ada göre sıralı getirir."""
        result = await self.db.execute(
            select(UnitModel)
            .where(UnitModel.company_id == company_id)
            .order_by(UnitModel.name)
        )
        return list(result.scalars().all())

    async def list_active(self, company_id: str) -> List[UnitModel]:
        """Sadece `company_id`'nin şu anda yönlendirme önerilerine uygun birimlerini getirir."""
        result = await self.db.execute(
            select(UnitModel)
            .where(UnitModel.company_id == company_id, UnitModel.is_active == True)  # noqa: E712
            .order_by(UnitModel.name)
        )
        return list(result.scalars().all())

    async def create(self, unit: UnitModel) -> UnitModel:
        """Yeni bir birim kaydını veritabanına kalıcı olarak yazar."""
        self.db.add(unit)
        await self.db.flush()
        return unit

    async def update(self, unit: UnitModel, update_data: dict) -> UnitModel:
        """Bir birim modelinin özniteliklerini günceller ve flush eder."""
        for field, value in update_data.items():
            if hasattr(unit, field) and value is not None:
                setattr(unit, field, value)
        await self.db.flush()
        return unit

    async def delete(self, unit_id: str, company_id: str) -> bool:
        """`company_id` kapsamında bir birim kaydını veritabanından kalıcı olarak kaldırır."""
        result = await self.db.execute(
            delete(UnitModel).where(UnitModel.id == unit_id, UnitModel.company_id == company_id)
        )
        await self.db.flush()
        return result.rowcount > 0


class UnitMembershipRepository:
    """Kullanıcı <-> birim bağlantısı için repository (bkz. `UnitMembershipModel`).

    Her metot açık bir `company_id` alır, yukarıdaki `UnitRepository` ile
    aynı kural.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, unit_id: str, user_id: str, company_id: str) -> Optional[UnitMembershipModel]:
        result = await self.db.execute(
            select(UnitMembershipModel).where(
                UnitMembershipModel.unit_id == unit_id,
                UnitMembershipModel.user_id == user_id,
                UnitMembershipModel.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_unit(self, unit_id: str, company_id: str) -> List[Tuple[UnitMembershipModel, UserModel]]:
        """`unit_id`'nin kimlikleriyle birleştirilmiş her üyesi, öneri için sıralanmış:
        önce birincil üyeler, sonra "lead"ler, sonra alfabetik olarak diğer herkes."""
        result = await self.db.execute(
            select(UnitMembershipModel, UserModel)
            .join(UserModel, UserModel.id == UnitMembershipModel.user_id)
            .where(UnitMembershipModel.unit_id == unit_id, UnitMembershipModel.company_id == company_id)
            .order_by(
                UnitMembershipModel.is_primary.desc(),
                (UnitMembershipModel.role_in_unit == "lead").desc(),
                UserModel.username.asc(),
            )
        )
        return [(membership, user) for membership, user in result.all()]

    async def get_primary_for_user(
        self, user_id: str, company_id: str
    ) -> Optional[UnitMembershipModel]:
        """`user_id` için (varsa) tek `is_primary=true` üyeliği.

        `TransferPolicy`'nin çapraz-birim (cross-unit) kontrolünde kullanılır:
        hiç birincil birimi olmayan bir alıcı, tek başına bir politika
        başarısızlığı değildir (cross_unit hesaplanamaz ve varsayılan olarak
        `False` olur, bkz. `TransferPolicy.evaluate`'in kendi docstring'i),
        sadece dürüstçe eksik bir sinyaldir.
        """
        result = await self.db.execute(
            select(UnitMembershipModel).where(
                UnitMembershipModel.user_id == user_id,
                UnitMembershipModel.company_id == company_id,
                UnitMembershipModel.is_primary.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def clear_primary_for_user(self, user_id: str, company_id: str) -> None:
        """`user_id` için var olan `is_primary` üyeliğin işaretini kaldırır.

        Yeni bir tanesini ayarlamadan önce çağrılır -- kısmi benzersiz indeks
        (`uq_unit_memberships_one_primary_per_user`) kullanıcı başına en
        fazla bir `is_primary=true` satırına izin verir, bu yüzden ikinci
        bir birimi birincil yapmak önce mevcut olanı düşürmeyi gerektirir.
        """
        result = await self.db.execute(
            select(UnitMembershipModel).where(
                UnitMembershipModel.user_id == user_id,
                UnitMembershipModel.company_id == company_id,
                UnitMembershipModel.is_primary.is_(True),
            )
        )
        for membership in result.scalars().all():
            membership.is_primary = False
        await self.db.flush()

    async def create(self, membership: UnitMembershipModel) -> UnitMembershipModel:
        self.db.add(membership)
        await self.db.flush()
        return membership

    async def delete(self, unit_id: str, user_id: str, company_id: str) -> bool:
        result = await self.db.execute(
            delete(UnitMembershipModel).where(
                UnitMembershipModel.unit_id == unit_id,
                UnitMembershipModel.user_id == user_id,
                UnitMembershipModel.company_id == company_id,
            )
        )
        await self.db.flush()
        return result.rowcount > 0
