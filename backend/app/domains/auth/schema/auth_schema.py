from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    """Giriş sırasında kimlik bilgilerini doğrulamak için Pydantic şeması."""
    username: str = Field(description="Kullanıcının kullanıcı adı veya e-posta adresi")
    password: str = Field(description="Ham hesap şifresi")

class TokenResponse(BaseModel):
    """Token yanıtı payload'u için Pydantic şeması."""
    access_token: str = Field(description="JWT Access Token")
    refresh_token: str = Field(description="JWT Refresh Token")
    token_type: str = Field(default="bearer", description="Token tipi ön eki")

class RefreshRequest(BaseModel):
    """Refresh token aracılığıyla access token yenileme için Pydantic şeması."""
    refresh_token: str = Field(description="Uzun ömürlü JWT Refresh Token")
