from typing import Optional, List
from uuid import uuid4

from app.domains.users.model.user_model import UserModel
from app.domains.users.model.invited_email import InvitedEmailModel
from app.domains.users.schema.user_schema import UserCreate, UserUpdate, PasswordChangeRequest
from app.domains.users.schema.invited_email import InvitedEmailCreate
from app.domains.users.repository import UserRepository
from app.core.security import hash_password, verify_password
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.authorization import AuthorizationException
from app.events import event_bus, UserCreatedEvent, UserDeletedEvent, UserPasswordChangedEvent


class UserService:
    """Kullanıcı ile ilgili iş kurallarını ve davetleri çalıştıran SOTA Servis."""

    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def register_user(self, schema: UserCreate) -> UserModel:
        """Önce davet beyaz listesini kontrol ederek ve davete özel rolü atayarak yeni bir kullanıcı kaydeder."""
        existing_user = await self.repository.get_by_username(schema.username)
        if existing_user:
            raise ConflictException(message="Username is already taken.")

        existing_email = await self.repository.get_by_email(schema.email)
        if existing_email:
            raise ConflictException(message="Email address is already in use.")

        # Beyaz liste (davet) kontrolü
        invite = await self.repository.get_invite_by_email(schema.email)
        if not invite:
            raise AuthorizationException(message="This email address has not been invited by a system administrator.")

        hashed = hash_password(schema.password)

        # Davette, davet eden admin/yönetici tarafından tanımlanan rol VE
        # şirketi zorunlu kıl -- kayıt olan kişinin ikisinden birini
        # seçmesine izin vermek, kendi kendine yetki yükseltme / kiracılar
        # arası kendi kendine atama açığı olurdu.
        user = UserModel(
            id=str(uuid4()),
            company_id=invite.company_id,
            username=schema.username,
            email=schema.email,
            hashed_password=hashed,
            role=invite.role,
            is_active=True,
            is_deleted=False
        )

        created_user = await self.repository.create(user)
        await self.repository.mark_invite_used(schema.email)

        # UserCreatedEvent'i yayınla
        await event_bus.publish(UserCreatedEvent(
            payload={
                "user_id": created_user.id,
                "username": created_user.username,
                "email": created_user.email,
                "role": created_user.role
            }
        ))

        return created_user

    async def invite_user_email(self, schema: InvitedEmailCreate, company_id: str) -> InvitedEmailModel:
        """`company_id`'ye kayıt için bir e-postayı davet eder/beyaz listeye alır (sadece Admin/Manager)."""
        registered = await self.repository.get_by_email(schema.email)
        if registered:
            raise ConflictException(message="A user with this email address is already registered.")

        existing_invite = await self.repository.get_invite_by_email(schema.email)
        if existing_invite:
            raise ConflictException(message="This email address has already been invited.")

        invite = InvitedEmailModel(
            id=str(uuid4()),
            company_id=company_id,
            email=schema.email,
            role=schema.role.value,
            is_used=False
        )

        return await self.repository.create_invite(invite)

    async def get_user_by_id(self, user_id: str) -> UserModel:
        """ID'ye göre kullanıcı getirir (şirket kapsamlı değildir), yoksa NotFoundException fırlatır.

        Sadece kimlik doğrulama yolu içindir (`get_current_user`) -- JWT'nin
        `sub`'ı zaten belirli bir satırı tanımlar, bu yüzden henüz kapsamına
        alınacak bir şirket yoktur. Başka bir kullanıcıya dönük admin/
        yönetici aramaları bunun yerine `get_user_by_id_in_company`
        kullanmalıdır.
        """
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundException(message="User not found.")
        return user

    async def get_user_by_id_in_company(self, user_id: str, company_id: str) -> UserModel:
        """`company_id` içinde ID'ye göre bir kullanıcı getirir, yoksa NotFoundException fırlatır."""
        user = await self.repository.get_by_id_in_company(user_id, company_id)
        if not user:
            raise NotFoundException(message="User not found.")
        return user

    async def get_users(
        self, company_id: str, skip: int = 0, limit: int = 100, role: Optional[str] = None
    ) -> List[UserModel]:
        """`company_id`'nin kullanıcı listesini sayfalama ve isteğe bağlı rol filtreleriyle getirir."""
        return await self.repository.get_multi(company_id, skip=skip, limit=limit, role=role)

    async def search_users(
        self,
        company_id: str,
        q: Optional[str] = None,
        unit_id: Optional[str] = None,
        role: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ):
        """Mesajlaşma/belge-transfer alıcı seçici (`GET /users/search`) için
        `company_id`'nin kullanıcılarını arar -- filtre semantiği için
        `UserRepository._search_query`'nin docstring'ine bakınız. Her
        kullanıcıyı birincil biriminin adıyla eşleştirerek döndürür.
        """
        items = await self.repository.search(
            company_id, q=q, unit_id=unit_id, role=role, skip=skip, limit=limit
        )
        total = await self.repository.count_search(company_id, q=q, unit_id=unit_id, role=role)
        return items, total

    async def update_user(self, user_id: str, schema: UserUpdate, company_id: str) -> UserModel:
        """E-posta değişirse benzersizlik kısıtlarını doğrulayarak kullanıcı detaylarını günceller.

        Args:
            company_id: İşlemi yapan adminin şirketi -- `user_id` bu şirkete
                ait olmalıdır, aksi halde bu, satır hiç var olmasaymış gibi
                aynı şekilde `NotFoundException` fırlatır (bir kullanıcı
                id'sinin farklı bir şirkette var olup olmadığını asla
                sızdırmaz).
        """
        user = await self.get_user_by_id_in_company(user_id, company_id)

        update_dict = schema.model_dump(exclude_unset=True)
        if "email" in update_dict and update_dict["email"] != user.email:
            existing = await self.repository.get_by_email(update_dict["email"])
            if existing:
                raise ConflictException(message="Email address is already in use.")

        if "role" in update_dict and update_dict["role"] is not None:
            update_dict["role"] = update_dict["role"].value

        if "clearance_level" in update_dict and update_dict["clearance_level"] is not None:
            update_dict["clearance_level"] = update_dict["clearance_level"].value

        return await self.repository.update(user, update_dict)

    async def change_password(self, user_id: str, schema: PasswordChangeRequest) -> None:
        """Mevcut parolayı doğruladıktan sonra kullanıcının parolasını değiştirir."""
        user = await self.get_user_by_id(user_id)

        if not verify_password(schema.current_password, user.hashed_password):
            raise AuthenticationException(message="Current password is incorrect.")

        hashed_new = hash_password(schema.new_password)
        await self.repository.update(user, {"hashed_password": hashed_new})

        # UserPasswordChangedEvent'i yayınla
        await event_bus.publish(UserPasswordChangedEvent(payload={"user_id": user_id}))

    async def soft_delete_user(self, user_id: str, company_id: str) -> None:
        """`company_id` kapsamında ID'ye göre kullanıcıyı soft-delete yapar."""
        user = await self.repository.soft_delete(user_id, company_id)
        if not user:
            raise NotFoundException(message="User not found.")

        # UserDeletedEvent'i yayınla (soft)
        await event_bus.publish(UserDeletedEvent(payload={"user_id": user_id, "delete_type": "soft"}))

    async def hard_delete_user(self, user_id: str, company_id: str) -> None:
        """`company_id` kapsamında ID'ye göre kullanıcıyı kalıcı olarak siler."""
        deleted = await self.repository.hard_delete(user_id, company_id)
        if not deleted:
            raise NotFoundException(message="User not found.")

        # UserDeletedEvent'i yayınla (hard)
        await event_bus.publish(UserDeletedEvent(payload={"user_id": user_id, "delete_type": "hard"}))
