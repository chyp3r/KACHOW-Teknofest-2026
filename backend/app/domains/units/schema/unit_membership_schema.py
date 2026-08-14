from typing import Optional

from pydantic import BaseModel, Field


class UnitMemberCreate(BaseModel):
    """Pydantic schema for adding a user to a unit."""

    user_id: str = Field(description="Birime eklenecek kullanıcının ID'si")
    is_primary: bool = Field(
        default=False, description="Bu kullanıcının birincil/ana birimi olarak işaretlensin mi"
    )
    role_in_unit: Optional[str] = Field(
        default=None, max_length=100, description="Örn. 'lead' -- serbest metin"
    )


class UnitMemberResponse(BaseModel):
    """Pydantic schema for a unit membership, joined with the member's basic identity."""

    user_id: str = Field(description="Kullanıcı ID")
    username: str = Field(description="Kullanıcı adı")
    email: str = Field(description="E-posta")
    is_primary: bool = Field(description="Bu kullanıcının birincil birimi mi")
    role_in_unit: Optional[str] = Field(default=None, description="Birim içindeki rolü")

    model_config = {"from_attributes": True}
