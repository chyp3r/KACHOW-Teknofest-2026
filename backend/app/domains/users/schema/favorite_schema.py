from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FavoriteCreateRequest(BaseModel):
    user_id: str = Field(description="Favorilere eklenecek kullanıcının ID'si")
    note: Optional[str] = Field(default=None, max_length=500)


class FavoriteResponse(BaseModel):
    id: str
    favorite_user_id: str
    username: str
    email: str
    note: Optional[str] = None
    created_at: datetime
