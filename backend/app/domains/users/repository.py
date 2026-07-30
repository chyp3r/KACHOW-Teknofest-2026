from typing import Optional, List
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.users.model.user_model import UserModel

class UserRepository:
    """SOTA Repository for SQLAlchemy database transactions regarding Users."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[UserModel]:
        """Fetch active user by primary key ID."""
        result = await self.db.execute(
            select(UserModel).where(UserModel.id == user_id, UserModel.is_deleted == False)
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

    async def get_multi(self, skip: int = 0, limit: int = 100, role: Optional[str] = None) -> List[UserModel]:
        """Fetch multiple users with pagination, filtering out soft-deleted ones."""
        query = select(UserModel).where(UserModel.is_deleted == False)
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

    async def soft_delete(self, user_id: str) -> Optional[UserModel]:
        """Mark a user as deleted and deactivate their account."""
        user = await self.get_by_id(user_id)
        if user:
            user.is_deleted = True
            user.is_active = False
            await self.db.flush()
        return user

    async def hard_delete(self, user_id: str) -> bool:
        """Permanently purge a user record from the database."""
        result = await self.db.execute(delete(UserModel).where(UserModel.id == user_id))
        await self.db.flush()
        return result.rowcount > 0
