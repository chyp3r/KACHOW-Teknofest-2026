from typing import Optional, List, Tuple
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.units.model.unit_membership_model import UnitMembershipModel
from app.domains.units.model.unit_model import UnitModel
from app.domains.users.model.user_model import UserModel
from app.domains.users.model.invited_email import InvitedEmailModel
from app.domains.users.model.user_favorite_model import UserFavoriteModel

class UserRepository:
    """SOTA Repository for SQLAlchemy database transactions regarding Users and Invites."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- User Methods ----------
    async def get_by_id(self, user_id: str) -> Optional[UserModel]:
        """Fetch active user by primary key ID.

        Deliberately not company-scoped: the JWT `sub` already identifies a
        specific row, so this is the low-level lookup used by
        `get_current_user` (before any company context is even resolved)
        and internally by service methods that apply their own company
        check afterwards (see `get_by_id_in_company`). Callers exposing a
        user by id to an admin/manager over the API must use
        `get_by_id_in_company` instead.
        """
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id, UserModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_by_id_in_company(self, user_id: str, company_id: str) -> Optional[UserModel]:
        """Fetch active user by ID, scoped to `company_id`.

        The tenant-safe variant of `get_by_id` -- an ADMIN/MANAGER managing
        users through the API must never be able to read or modify another
        company's user by simply guessing/enumerating an id.
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
        """Fetch active user by unique email."""
        result = await self.db.execute(
            select(UserModel).where(UserModel.email == email, UserModel.is_deleted == False)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[UserModel]:
        """Fetch active user by unique username."""
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
        """Fetch multiple users of `company_id` with pagination, filtering out soft-deleted ones."""
        query = select(UserModel).where(
            UserModel.company_id == company_id, UserModel.is_deleted == False
        )
        if role:
            query = query.where(UserModel.role == role)
        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(self, user: UserModel) -> UserModel:
        """Persist a new user record in the database."""
        self.db.add(user)
        await self.db.flush()
        return user

    async def update(self, user: UserModel, update_data: dict) -> UserModel:
        """Update attributes of a user model and commit/flush."""
        for field, value in update_data.items():
            if hasattr(user, field) and value is not None:
                setattr(user, field, value)
        await self.db.flush()
        return user

    async def soft_delete(self, user_id: str, company_id: str) -> Optional[UserModel]:
        """Mark a user as deleted and deactivate their account, scoped to `company_id`."""
        user = await self.get_by_id_in_company(user_id, company_id)
        if user:
            user.is_deleted = True
            user.is_active = False
            await self.db.flush()
        return user

    async def hard_delete(self, user_id: str, company_id: str) -> bool:
        """Permanently purge a user record from the database, scoped to `company_id`."""
        result = await self.db.execute(
            delete(UserModel).where(UserModel.id == user_id, UserModel.company_id == company_id)
        )
        await self.db.flush()
        return result.rowcount > 0

    # ---------- Invite Methods ----------
    async def get_invite_by_email(self, email: str) -> Optional[InvitedEmailModel]:
        """Fetch active, unused invite by email."""
        result = await self.db.execute(
            select(InvitedEmailModel).where(
                InvitedEmailModel.email == email,
                InvitedEmailModel.is_used == False
            )
        )
        return result.scalar_one_or_none()

    async def create_invite(self, invite: InvitedEmailModel) -> InvitedEmailModel:
        """Persist a new email invitation whitelist record."""
        self.db.add(invite)
        await self.db.flush()
        return invite

    async def mark_invite_used(self, email: str) -> bool:
        """Mark email invitation as used."""
        invite = await self.get_invite_by_email(email)
        if invite:
            invite.is_used = True
            await self.db.flush()
            return True
        return False

    # ---------- Search ----------

    def _search_query(
        self,
        company_id: str,
        q: Optional[str],
        unit_id: Optional[str],
        role: Optional[str],
    ):
        """Shared filtered query for `search`/`count_search`.

        `q` matches `username`/`email` (case-insensitive substring) --
        `UserModel` has no separate display-name column today, so "isim"
        search is a username/email match, same as every other user-facing
        list in this codebase. `unit_id` matches *any* of a user's unit
        memberships (not only the primary one `search` also returns).
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
        """Search company users, each paired with its primary unit's name
        (`None` if the user has no primary unit membership) -- see
        `_search_query` for the filter semantics.
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
    """Repository for `user_favorites` (see `UserFavoriteModel`).

    Every method is scoped to `owner_user_id` -- a favorite is a one-
    directional, per-user list, never a company-wide or shared resource.
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
        """`owner_user_id`'s favorites, joined with the favorited user's
        identity, newest-favorited first."""
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
