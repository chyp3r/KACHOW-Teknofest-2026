from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.users.model.user_model import UserModel

class UserRepository:
    """SOTA Repository for SQLAlchemy database transactions regarding Users."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str) -> Optional[UserModel]:
        """Fetch user by primary key ID."""
        result = await self.db.execute(select(UserModel).where(UserModel.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[UserModel]:
        """Fetch user by unique email."""
        result = await self.db.execute(select(UserModel).where(UserModel.email == email))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[UserModel]:
        """Fetch user by unique username."""
        result = await self.db.execute(select(UserModel).where(UserModel.username == username))
        return result.scalar_one_or_none()

    async def create(self, user: UserModel) -> UserModel:
        """Persist a new user record in the database."""
        self.db.add(user)
        await self.db.flush()
        return user
