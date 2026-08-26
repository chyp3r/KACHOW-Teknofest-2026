from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole

class UserCreate(BaseModel):
    """Yeni bir kullanıcı hesabı oluşturmak için Pydantic şeması.

    Kasıtlı olarak ``clearance_level`` alanı yoktur: kayıt self-servistir
    (sadece davet beyaz listesi ile kısıtlanır, kimlik doğrulama gerekmez),
    bu yüzden kayıt olan kişinin kendi gizlilik tavanını belirlemesine izin
    vermek, kendi kendine yetki yükseltme açığı olurdu. Her yeni hesap
    ``UserModel.clearance_level``'ın kolon varsayılanıyla başlar ve sonradan
    sadece bir admin tarafından ``PUT /users/{id}`` ile yükseltilebilir.
    """
    username: str = Field(description="Benzersiz kullanıcı adı")
    email: EmailStr = Field(description="Benzersiz e-posta adresi")
    password: str = Field(description="Düz metin parola")
    role: UserRole = Field(default=UserRole.EMPLOYEE, description="Yetkilendirme için atanan rol")

class UserUpdate(BaseModel):
    """Bir kullanıcı hesabını güncellemek için Pydantic şeması."""
    email: Optional[EmailStr] = Field(default=None, description="İsteğe bağlı güncellenmiş e-posta adresi")
    role: Optional[UserRole] = Field(default=None, description="İsteğe bağlı güncellenmiş yetkilendirme rolü")
    is_active: Optional[bool] = Field(default=None, description="İsteğe bağlı güncellenmiş kullanıcı hesabı durumu")
    clearance_level: Optional[SensitivityLevel] = Field(
        default=None,
        description=(
            "İsteğe bağlı güncellenmiş gizlilik tavanı (sadece EMPLOYEE rolü için -- "
            "ADMIN/MANAGER bu değerden bağımsız olarak her şeyi geçer). "
            "role/is_active gibi sadece admin için."
        ),
    )

class PasswordChangeRequest(BaseModel):
    """Mevcut kullanıcının parolasını güvenli şekilde güncellemek için Pydantic şeması."""
    current_password: str = Field(description="Kullanıcının mevcut parolası")
    new_password: str = Field(description="Kullanıcının yeni güvenli parolası")

class UserResponse(BaseModel):
    """Kullanıcı hesabı detayları çıktısı için Pydantic şeması."""
    id: str = Field(description="Benzersiz kullanıcı ID'si")
    company_id: Optional[str] = Field(default=None, description="Sahip şirket (root için NULL)")
    username: str = Field(description="Benzersiz kullanıcı adı")
    email: EmailStr = Field(description="Benzersiz e-posta adresi")
    role: UserRole = Field(description="Atanan yetkilendirme rolü")
    clearance_level: SensitivityLevel = Field(description="Gizlilik tavanı (sadece EMPLOYEE rolü için).")
    is_active: bool = Field(description="Kullanıcı hesabının durumu")
    is_deleted: bool = Field(description="Soft delete bayrağının durumu")

    model_config = {
        "from_attributes": True
    }
