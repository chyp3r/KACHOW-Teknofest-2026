import logging
from typing import List, Tuple
from uuid import uuid4

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.conflict import ConflictException
from app.api.exceptions.not_found import NotFoundException
from app.domains.users.model.user_favorite_model import UserFavoriteModel
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserFavoriteRepository, UserRepository

logger = logging.getLogger(__name__)


class FavoriteService:
    """`user_favorites` için servis.

    Simetrik değildir ve şirket tarafından yönetilmez: bir favori, bir
    kullanıcının kendi diğer kullanıcılar listesidir, tamamen
    `owner_user_id` kapsamındadır -- bunun neden var olduğu için
    `UserFavoriteModel`'in docstring'ine bakınız (AI destekli belge/evrak
    transfer akışı, Faz 4, kullanıcı adına herhangi bir şey gönderebilmeden
    önce alıcının zaten favori olmasını gerektirecek).
    """

    def __init__(self, favorite_repository: UserFavoriteRepository, user_repository: UserRepository):
        self.favorite_repository = favorite_repository
        self.user_repository = user_repository

    async def add_favorite(
        self, company_id: str, owner: UserModel, favorite_user_id: str, note: str | None
    ) -> Tuple[UserFavoriteModel, UserModel]:
        if favorite_user_id == owner.id:
            raise AuthorizationException(message="Kendinizi favorilere ekleyemezsiniz.")

        favorite_user = await self.user_repository.get_by_id_in_company(favorite_user_id, company_id)
        if favorite_user is None:
            raise NotFoundException(message="Kullanıcı bulunamadı.")

        existing = await self.favorite_repository.get(owner.id, favorite_user_id, company_id)
        if existing is not None:
            raise ConflictException(message="Bu kullanıcı zaten favorilerinizde.")

        favorite = await self.favorite_repository.create(
            UserFavoriteModel(
                id=uuid4().hex,
                company_id=company_id,
                owner_user_id=owner.id,
                favorite_user_id=favorite_user_id,
                note=note,
            )
        )
        return favorite, favorite_user

    async def remove_favorite(self, company_id: str, owner: UserModel, favorite_user_id: str) -> None:
        deleted = await self.favorite_repository.delete(owner.id, favorite_user_id, company_id)
        if not deleted:
            raise NotFoundException(message="Bu kullanıcı favorilerinizde değil.")

    async def list_favorites(
        self, company_id: str, owner: UserModel
    ) -> List[Tuple[UserFavoriteModel, UserModel]]:
        return await self.favorite_repository.list_for_owner(owner.id, company_id)
