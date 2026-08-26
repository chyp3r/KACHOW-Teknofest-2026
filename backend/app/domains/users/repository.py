from typing import Optional, List, Tuple
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.users.model.user_model import UserModel
from app.domains.users.model.invited_email import InvitedEmailModel
from app.domains.users.model.user_favorite_model import UserFavoriteModel

class UserRepository:
    """Kullanıcılar ve Davetler ile ilgili SQLAlchemy veritabanı işlemleri için SOTA Repository."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- Kullanıcı Metotları ----------
    async def get_by_id(self, user_id: str) -> Optional[UserModel]:
        """Birincil anahtar ID'sine göre aktif kullanıcı getirir.

        Kasıtlı olarak şirket kapsamlı değildir: JWT'nin `sub`'ı zaten
        belirli bir satırı tanımlar, bu yüzden bu, `get_current_user`
        tarafından (herhangi bir şirket bağlamı çözülmeden önce) ve
        sonradan kendi şirket kontrolünü uygulayan servis metotları
        tarafından dahili olarak kullanılan düşük seviye arama işlemidir
        (bkz. `get_by_id_in_company`). Bir kullanıcıyı API üzerinden
        admin/yöneticiye id ile açığa çıkaran çağıranlar bunun yerine
        `get_by_id_in_company` kullanmalıdır.
        """
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id, UserModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_by_id_in_company(self, user_id: str, company_id: str) -> Optional[UserModel]:
        """`company_id` kapsamında, ID'ye göre aktif kullanıcı getirir.

        `get_by_id`'nin kiracı-güvenli varyantı -- API üzerinden kullanıcı
        yöneten bir ADMIN/MANAGER, sadece bir id tahmin ederek/numaralandırarak
        başka bir şirketin kullanıcısını asla okuyabilmemeli veya
        değiştirebilmemelidir.
        """
        result = await self.db.execute(
            select(UserModel).where(
                UserModel.id == user_id,
                UserModel.company_id == company_id,
                UserModel.is_deleted == False,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[UserModel]:
        """Benzersiz e-postaya göre aktif kullanıcı getirir."""
        result = await self.db.execute(
            select(UserModel).where(UserModel.email == email, UserModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[UserModel]:
        """Benzersiz kullanıcı adına göre aktif kullanıcı getirir."""
        result = await self.db.execute(
            select(UserModel).where(UserModel.username == username, UserModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        company_id: str,
        skip: int = 0,
        limit: int = 100,
        role: Optional[str] = None,
    ) -> List[UserModel]:
        """`company_id`'nin birden fazla kullanıcısını sayfalama ile getirir, soft-delete olanları filtreler."""
        query = select(UserModel).where(
            UserModel.company_id == company_id, UserModel.is_deleted == False
        )
        if role:
            query = query.where(UserModel.role == role)
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, user: UserModel) -> UserModel:
        """Yeni bir kullanıcı kaydını veritabanına kalıcı olarak yazar."""
        self.db.add(user)
        await self.db.flush()
        return user

    async def update(self, user: UserModel, update_data: dict) -> UserModel:
        """Bir kullanıcı modelinin özniteliklerini günceller ve commit/flush eder."""
        for field, value in update_data.items():
            if hasattr(user, field) and value is not None:
                setattr(user, field, value)
        await self.db.flush()
        return user

    async def soft_delete(self, user_id: str, company_id: str) -> Optional[UserModel]:
        """`company_id` kapsamında bir kullanıcıyı silinmiş olarak işaretler ve hesabını pasifleştirir."""
        user = await self.get_by_id_in_company(user_id, company_id)
        if user:
            user.is_deleted = True
            user.is_active = False
            await self.db.flush()
        return user

    async def hard_delete(self, user_id: str, company_id: str) -> bool:
        """`company_id` kapsamında bir kullanıcı kaydını veritabanından kalıcı olarak siler."""
        result = await self.db.execute(
            delete(UserModel).where(UserModel.id == user_id, UserModel.company_id == company_id)
        )
        await self.db.flush()
        return result.rowcount > 0

    # ---------- Davet Metotları ----------
    async def get_invite_by_email(self, email: str) -> Optional[InvitedEmailModel]:
        """E-postaya göre aktif, kullanılmamış daveti getirir."""
        result = await self.db.execute(
            select(InvitedEmailModel).where(
                InvitedEmailModel.email == email,
                InvitedEmailModel.is_used == False
            )
        )
        return result.scalar_one_or_none()

    async def create_invite(self, invite: InvitedEmailModel) -> InvitedEmailModel:
        """Yeni bir e-posta davet beyaz liste kaydını kalıcı olarak yazar."""
        self.db.add(invite)
        await self.db.flush()
        return invite

    async def mark_invite_used(self, email: str) -> bool:
        """E-posta davetini kullanıldı olarak işaretler."""
        invite = await self.get_invite_by_email(email)
        if invite:
            invite.is_used = True
            await self.db.flush()
            return True
        return False

    # ---------- Arama ----------

    def _search_query(
        self,
        company_id: str,
        q: Optional[str],
        unit_id: Optional[str],
        role: Optional[str],
    ):
        """`search`/`count_search` için ortak filtrelenmiş sorgu.

        `q`, `username`/`email` ile eşleşir (büyük/küçük harf duyarsız alt
        dize) -- `UserModel`'in bugün ayrı bir görünen-ad kolonu yok, bu
        yüzden "isim" araması, bu kod tabanındaki diğer her kullanıcıya
        dönük liste gibi bir username/email eşleşmesidir. `unit_id`,
        bir kullanıcının birim üyeliklerinden *herhangi biriyle* eşleşir
        (sadece `search`'ün de döndürdüğü birincil olanla değil).
        """
        query = select(UserModel).where(
            UserModel.company_id == company_id, UserModel.is_deleted.is_(False)
        )
        if q:
            pattern = f"%{q}%"
            query = query.where(or_(UserModel.username.ilike(pattern), UserModel.email.ilike(pattern)))
        if role:
            query = query.where(UserModel.role == role)
        if unit_id:
            query = query.where(
                exists().where(
                    UnitMembershipModel.user_id == UserModel.id,
                    UnitMembershipModel.company_id == company_id,
                    UnitMembershipModel.unit_id == unit_id,
                )
            )
        return query

    async def search(
        self,
        company_id: str,
        q: Optional[str] = None,
        unit_id: Optional[str] = None,
        role: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Tuple[UserModel, Optional[str]]]:
        """Şirket kullanıcılarını arar, her birini birincil biriminin adıyla
        eşleştirir (kullanıcının birincil birim üyeliği yoksa `None`) --
        filtre semantiği için `_search_query`'ye bakınız.
        """
        primary_unit_name = (
            select(UnitModel.name)
            .join(UnitMembershipModel, UnitMembershipModel.unit_id == UnitModel.id)
            .where(
                UnitMembershipModel.user_id == UserModel.id,
                UnitMembershipModel.company_id == company_id,
                UnitMembershipModel.is_primary.is_(True),
            )
            .correlate(UserModel)
            .scalar_subquery()
        )
        query = (
            self._search_query(company_id, q, unit_id, role)
            .add_columns(primary_unit_name.label("unit_name"))
            .order_by(UserModel.username.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return [(user, unit_name) for user, unit_name in result.all()]

    async def count_search(
        self,
        company_id: str,
        q: Optional[str] = None,
        unit_id: Optional[str] = None,
        role: Optional[str] = None,
    ) -> int:
        query = select(func.count()).select_from(
            self._search_query(company_id, q, unit_id, role).subquery()
        )
        result = await self.db.execute(query)
        return result.scalar_one()


class UserFavoriteRepository:
    """`user_favorites` için repository (bkz. `UserFavoriteModel`).

    Her metot `owner_user_id` kapsamındadır -- bir favori, tek yönlü,
    kullanıcı başına bir listedir, asla şirket genelinde veya paylaşılan
    bir kaynak değildir.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, owner_user_id: str, favorite_user_id: str, company_id: str
    ) -> Optional[UserFavoriteModel]:
        result = await self.db.execute(
            select(UserFavoriteModel).where(
                UserFavoriteModel.owner_user_id == owner_user_id,
                UserFavoriteModel.favorite_user_id == favorite_user_id,
                UserFavoriteModel.company_id == company_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, favorite: UserFavoriteModel) -> UserFavoriteModel:
        self.db.add(favorite)
        await self.db.flush()
        return favorite

    async def delete(self, owner_user_id: str, favorite_user_id: str, company_id: str) -> bool:
        result = await self.db.execute(
            delete(UserFavoriteModel).where(
                UserFavoriteModel.owner_user_id == owner_user_id,
                UserFavoriteModel.favorite_user_id == favorite_user_id,
                UserFavoriteModel.company_id == company_id,
            )
        )
        await self.db.flush()
        return result.rowcount > 0

    async def list_for_owner(
        self, owner_user_id: str, company_id: str
    ) -> List[Tuple[UserFavoriteModel, UserModel]]:
        """`owner_user_id`'nin, favorilenen kullanıcının kimliğiyle
        birleştirilmiş favorileri, en yeni favorilenen önce."""
        result = await self.db.execute(
            select(UserFavoriteModel, UserModel)
            .join(UserModel, UserModel.id == UserFavoriteModel.favorite_user_id)
            .where(
                UserFavoriteModel.owner_user_id == owner_user_id,
                UserFavoriteModel.company_id == company_id,
            )
            .order_by(UserFavoriteModel.created_at.desc())
        )
        return [(favorite, user) for favorite, user in result.all()]

    async def is_favorite(self, owner_user_id: str, favorite_user_id: str, company_id: str) -> bool:
        result = await self.db.execute(
            select(
                exists().where(
                    UserFavoriteModel.owner_user_id == owner_user_id,
                    UserFavoriteModel.favorite_user_id == favorite_user_id,
                    UserFavoriteModel.company_id == company_id,
                )
            )
        )
        return bool(result.scalar())
