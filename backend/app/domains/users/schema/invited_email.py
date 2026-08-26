from pydantic import BaseModel, EmailStr, Field
from app.core.enums.user_role import UserRole

class InvitedEmailCreate(BaseModel):
    """Bir e-postayı beyaz listeye alma/davet etme için Pydantic şeması."""
    email: EmailStr = Field(description="Davet edilen e-posta adresi")
    role: UserRole = Field(default=UserRole.EMPLOYEE, description="Davet edilen kişiye önceden atanmış rol")

class InvitedEmailResponse(BaseModel):
    """Beyaz listeye alınmış/davet edilmiş e-posta detaylarını döndüren Pydantic şeması."""
    id: str = Field(description="Benzersiz davet ID'si")
    email: EmailStr = Field(description="Davet edilen e-posta adresi")
    role: UserRole = Field(description="Önceden atanmış rol")
    company_id: str = Field(description="Davet edilen kişinin kayıt sonrası katılacağı şirket")
    is_used: bool = Field(description="Davetin kullanım durumu")

    model_config = {
        "from_attributes": True
    }
