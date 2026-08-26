from typing import Optional

from pydantic import BaseModel, EmailStr

from app.core.enums.user_role import UserRole


class UserSearchResult(BaseModel):
    """Bir `GET /users/search` satırı -- `UserResponse` artı sade bir
    kullanıcı getirmede taşınmasına gerek olmayan, sadece aramaya özel
    bağlam (`unit_name`, `is_favorite`)."""

    id: str
    username: str
    email: EmailStr
    role: UserRole
    unit_name: Optional[str] = None
    is_favorite: bool = False
