"""Güvenlik araçları: JWT token üretimi ve parola hashleme.

Parola hashleme `bcrypt` gerektirir.
JWT imzalama `pyjwt` gerektirir.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import bcrypt
import jwt

from app.core.config import settings
from app.api.exceptions.authentication import AuthenticationException

logger = logging.getLogger(__name__)

# ---------- Sabitler ----------
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30


# ---------- Parola Hashleme ----------
def hash_password(plain_password: str) -> str:
    """Düz metin bir parolayı bcrypt kullanarak hashle."""
    return bcrypt.hashpw(
        plain_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Düz metin bir parolayı bir bcrypt hash'ine karşı doğrula."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception as e:
        logger.error(f"Password verification failed due to error: {e}")
        return False


# ---------- JWT Token Üretimi ----------
def create_access_token(subject: str | Any, extra_claims: dict | None = None) -> str:
    """Verilen özne için kısa ömürlü bir JWT erişim token'ı oluştur."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(subject: str | Any) -> str:
    """Verilen özne için uzun ömürlü bir JWT yenileme token'ı oluştur."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Bir JWT token'ını çöz ve doğrula, payload'ını döndür."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError as exc:
        raise AuthenticationException(message="Invalid or expired token.") from exc
