"""Güvenlik yardımcı araçları: JWT üretimi ve parola hashing.

Not:
    JWT imzalama için `python-jose[cryptography]` veya `pyjwt`,
    parola hashing için `passlib[bcrypt]` gereklidir.
    Bu modül, henüz kurulmayan bu kütüphaneler için taslak (skeleton) olarak
    tasarlanmıştır. Bağımlılıklar requirements.txt'e eklendiğinde
    içe aktarma satırlarının yorumdan çıkarılması yeterlidir.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

# Gerçek kullanımda bu satırları yorumdan çıkarın:
# from jose import JWTError, jwt
# from passlib.context import CryptContext

from app.core.config import settings

# ---------- Sabitler ----------
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# ---------- Hashing (Skeleton) ----------
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Verilen düz metni bcrypt ile hash'ler.

    Bağımlılıklar kurulduktan sonra aşağıdaki satırı etkinleştirin:
        return pwd_context.hash(plain_password)
    """
    raise NotImplementedError(
        "passlib[bcrypt] kurulumu tamamlandığında bu metodu etkinleştirin."
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verilen düz metin ile hash eşleşip eşleşmediğini kontrol eder.

    Bağımlılıklar kurulduktan sonra aşağıdaki satırı etkinleştirin:
        return pwd_context.verify(plain_password, hashed_password)
    """
    raise NotImplementedError(
        "passlib[bcrypt] kurulumu tamamlandığında bu metodu etkinleştirin."
    )


# ---------- JWT (Skeleton) ----------

def create_access_token(subject: str | Any, extra_claims: dict | None = None) -> str:
    """Verilen konu (subject) için kısa ömürlü erişim jetonu üretir.

    Args:
        subject: Token'ın sahibini temsil eden değer (örn. kullanıcı ID'si).
        extra_claims: JWT payload'ına eklenecek ek bilgiler (örn. rol, scope).

    Returns:
        İmzalanmış JWT string'i.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    # Gerçek kullanımda:
    #   return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    raise NotImplementedError(
        "python-jose[cryptography] kurulumu tamamlandığında bu metodu etkinleştirin."
    )


def create_refresh_token(subject: str | Any) -> str:
    """Verilen konu için uzun ömürlü yenileme jetonu üretir."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    # return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    raise NotImplementedError(
        "python-jose[cryptography] kurulumu tamamlandığında bu metodu etkinleştirin."
    )


def decode_token(token: str) -> dict[str, Any]:
    """JWT'yi doğrular ve payload sözlüğünü döndürür.

    Raises:
        AuthenticationException: Token geçersiz veya süresi dolmuşsa.
    """
    # try:
    #     payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    #     return payload
    # except JWTError as exc:
    #     from app.api.exceptions.authentication import AuthenticationException
    #     raise AuthenticationException(message="Geçersiz veya süresi dolmuş jeton.") from exc
    raise NotImplementedError(
        "python-jose[cryptography] kurulumu tamamlandığında bu metodu etkinleştirin."
    )
