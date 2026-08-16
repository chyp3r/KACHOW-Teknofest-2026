from typing import Optional

from pydantic import BaseModel, EmailStr

from app.core.enums.user_role import UserRole


class UserSearchResult(BaseModel):
    """One `GET /users/search` row -- `UserResponse` plus search-only
    context (`unit_name`, `is_favorite`) that a plain user fetch has no
    reason to carry."""

    id: str
    username: str
    email: EmailStr
    role: UserRole
    unit_name: Optional[str] = None
    is_favorite: bool = False
