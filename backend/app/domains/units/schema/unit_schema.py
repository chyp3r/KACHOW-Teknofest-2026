from typing import Optional

from pydantic import BaseModel, Field


class UnitCreate(BaseModel):
    """Pydantic schema for creating a new routable unit."""

    name: str = Field(min_length=1, max_length=200, description="Birimin adı (benzersiz)")
    description: str = Field(
        min_length=1,
        max_length=2000,
        description="Birimin hangi konuları/talepleri kapsadığı -- AI yönlendirme kararında bunu okur",
    )


class UnitUpdate(BaseModel):
    """Pydantic schema for updating an existing unit. All fields optional."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    is_active: Optional[bool] = Field(
        default=None, description="False ise birim yönlendirme önerilerinden hariç tutulur"
    )


class UnitResponse(BaseModel):
    """Pydantic schema for unit details output."""

    id: str = Field(description="Birim ID")
    name: str = Field(description="Birim adı")
    description: str = Field(description="Birim açıklaması")
    is_active: bool = Field(description="Birimin yönlendirme önerilerinde aktif olup olmadığı")

    model_config = {"from_attributes": True}
