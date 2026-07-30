from typing import Optional, List
from uuid import uuid4

from app.domains.users.model.user_model import UserModel
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest
from app.domains.users.repository import UserRepository
from app.core.security import hash_password, verify_password
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.authentication import AuthenticationException

class UserService:
    """SOTA Service executing user-related business rules."""

    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def register_user(self, schema: UserCreate) -> UserModel:
        """Register a new user, hash their password, and persist to database."""
        existing_user = await self.repository.get_by_username(schema.username)
        if existing_user:
            raise ConflictException(message="Bu kullanıcı adı zaten alınmış.")

        existing_email = await self.repository.get_by_email(schema.email)
        if existing_email:
            raise ConflictException(message="Bu e-posta adresi zaten kullanımda.")

        hashed = hash_password(schema.password)
        
        user = UserModel(
            id=str(uuid4()),
            username=schema.username,
            email=schema.email,
            hashed_password=hashed,
            role=schema.role.value,
            is_active=True,
            is_deleted=False
        )

        return await self.repository.create(user)

    async def get_user_by_id(self, user_id: str) -> UserModel:
        """Fetch user by ID, raising NotFoundException if not present."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(message="Kullanıcı bulunamadı.")
        return user

    async def get_users(self, skip: int = 0, limit: int = 100, role: Optional[str] = None) -> List[UserModel]:
        """Fetch list of users with pagination and optional role filters."""
        return await self.repository.get_multi(skip=skip, limit=limit, role=role)

    async def update_user(self, user_id: str, schema: UserUpdate) -> UserModel:
        """Update user details, verifying unique constraints if email changes."""
        user = await self.get_user_by_id(user_id)
        
        update_dict = schema.model_dump(exclude_unset=True)
        if "email" in update_dict and update_dict["email"] != user.email:
            existing = await self.repository.get_by_email(update_dict["email"])
            if existing:
                raise ConflictException(message="Bu e-posta adresi zaten kullanımda.")
        
        if "role" in update_dict and update_dict["role"] is not None:
            update_dict["role"] = update_dict["role"].value

        return await self.repository.update(user, update_dict)

    async def change_password(self, user_id: str, schema: PasswordChangeRequest) -> None:
        """Change the password of the user after verifying current password."""
        user = await self.get_user_by_id(user_id)
        
        if not verify_password(schema.current_password, user.hashed_password):
            raise AuthenticationException(message="Mevcut şifreniz hatalı.")

        hashed_new = hash_password(schema.new_password)
        await self.repository.update(user, {"hashed_password": hashed_new})

    async def soft_delete_user(self, user_id: str) -> None:
        """Soft delete user by ID."""
        user = await self.repository.soft_delete(user_id)
        if not user:
            raise NotFoundException(message="Kullanıcı bulunamadı.")

    async def hard_delete_user(self, user_id: str) -> None:
        """Hard delete user by ID."""
        deleted = await self.repository.hard_delete(user_id)
        if not deleted:
            raise NotFoundException(message="Kullanıcı bulunamadı.")
