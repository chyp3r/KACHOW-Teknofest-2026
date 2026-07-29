"""Security utilities: JWT token generation and password hashing.

Note:
    JWT signing requires `python-jose[cryptography]` or `pyjwt`.
    Password hashing requires `passlib[bcrypt]`.
    This module is structured as a ready-to-activate skeleton.
    Once the dependencies are added to requirements.txt, uncomment the
    relevant import lines and remove the NotImplementedError stubs.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings

# ---------- Constants ----------
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# ---------- Password Hashing (Skeleton) ----------
# Activate after adding passlib[bcrypt] to requirements.txt:
# from passlib.context import CryptContext
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password using bcrypt.

    Args:
        plain_password: The raw password string to hash.

    Returns:
        The bcrypt-hashed password string.

    Raises:
        NotImplementedError: Until passlib[bcrypt] is installed.
    """
    # return pwd_context.hash(plain_password)
    raise NotImplementedError("Activate after installing passlib[bcrypt].")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash.

    Args:
        plain_password: The raw password provided by the user.
        hashed_password: The stored bcrypt hash to compare against.

    Returns:
        True if the password matches, False otherwise.

    Raises:
        NotImplementedError: Until passlib[bcrypt] is installed.
    """
    # return pwd_context.verify(plain_password, hashed_password)
    raise NotImplementedError("Activate after installing passlib[bcrypt].")


# ---------- JWT Token Generation (Skeleton) ----------
# Activate after adding python-jose[cryptography] to requirements.txt:
# from jose import JWTError, jwt


def create_access_token(subject: str | Any, extra_claims: dict | None = None) -> str:
    """Create a short-lived JWT access token for the given subject.

    Args:
        subject: The identity the token represents (e.g., user ID).
        extra_claims: Additional key-value pairs to embed in the JWT payload (e.g., role, scope).

    Returns:
        A signed JWT string.

    Raises:
        NotImplementedError: Until python-jose[cryptography] is installed.
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

    # return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    raise NotImplementedError("Activate after installing python-jose[cryptography].")


def create_refresh_token(subject: str | Any) -> str:
    """Create a long-lived JWT refresh token for the given subject.

    Args:
        subject: The identity the token represents (e.g., user ID).

    Returns:
        A signed JWT string.

    Raises:
        NotImplementedError: Until python-jose[cryptography] is installed.
    """
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh",
    }
    # return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    raise NotImplementedError("Activate after installing python-jose[cryptography].")


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token, returning its payload.

    Args:
        token: The raw JWT string to decode.

    Returns:
        The decoded payload dictionary.

    Raises:
        AuthenticationException: If the token is invalid or expired.
        NotImplementedError: Until python-jose[cryptography] is installed.
    """
    # try:
    #     payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    #     return payload
    # except JWTError as exc:
    #     from app.api.exceptions.authentication import AuthenticationException
    #     raise AuthenticationException(message="Invalid or expired token.") from exc
    raise NotImplementedError("Activate after installing python-jose[cryptography].")
