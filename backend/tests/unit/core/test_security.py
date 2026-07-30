import pytest
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.api.exceptions.authentication import AuthenticationException

def test_password_hashing():
    password = "mysecurepassword"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_jwt_tokens():
    subject = "user123"
    claims = {"role": "admin", "username": "john"}
    access_token = create_access_token(subject, extra_claims=claims)
    refresh_token = create_refresh_token(subject)
    
    assert access_token is not None
    assert refresh_token is not None
    
    payload = decode_token(access_token)
    assert payload["sub"] == subject
    assert payload["role"] == "admin"
    assert payload["username"] == "john"
    assert payload["type"] == "access"
    
    refresh_payload = decode_token(refresh_token)
    assert refresh_payload["sub"] == subject
    assert refresh_payload["type"] == "refresh"

def test_invalid_token():
    with pytest.raises(AuthenticationException):
        decode_token("invalid.token.string")
