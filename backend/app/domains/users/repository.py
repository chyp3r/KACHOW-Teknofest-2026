from typing import Optional, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.users.model.user_model import UserModel
from app.domains.users.model.invited_email import InvitedEmailModel

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
