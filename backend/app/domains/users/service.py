from uuid import uuid4
from app.domains.users.model.user_model import UserModel
from app.domains.users.schema.user_schema import UserCreate
from app.domains.users.repository import UserRepository
from app.core.security import hash_password
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException

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
            is_active=True
        )

        return await self.repository.create(user)

    async def get_user_by_id(self, user_id: str) -> UserModel:
        """Fetch user by ID, raising NotFoundException if not present."""
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(message="Kullanıcı bulunamadı.")
        return user
