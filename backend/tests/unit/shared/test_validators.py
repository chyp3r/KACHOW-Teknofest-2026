import pytest
import uuid
from app.shared.validator.email_validator import validate_email
from app.shared.validator.phone_validator import validate_phone
from app.shared.validator.uuid_validator import validate_uuid
from app.shared.validator.file_validator import validate_file_extension
def test_validate_email_valid():
    assert validate_email("test@example.com") == "test@example.com"

def test_validate_email_invalid():
    with pytest.raises(ValueError):
        validate_email("test@")
    with pytest.raises(ValueError):
        validate_email("test")

def test_validate_phone_valid():
    assert validate_phone("+1234567890") == "+1234567890"
    assert validate_phone("  +1234567890  ") == "+1234567890"
    assert validate_phone("1234567890") == "1234567890"

def test_validate_phone_invalid():
    with pytest.raises(ValueError):
        validate_phone("abc")
    with pytest.raises(ValueError):
        validate_phone("+1234567890123456")

def test_validate_uuid_valid():
    val = str(uuid.uuid4())
    assert validate_uuid(val) == val

def test_validate_uuid_invalid():
    with pytest.raises(ValueError):
        validate_uuid("invalid-uuid")
    with pytest.raises(ValueError):
        validate_uuid("123")

def test_validate_file_extension_valid():
    assert validate_file_extension("test.pdf", [".pdf", ".txt"]) is True
    assert validate_file_extension("test.PDF", [".pdf"]) is True

def test_validate_file_extension_invalid():
    assert validate_file_extension("test.doc", [".pdf"]) is False
    assert validate_file_extension("test", [".pdf"]) is False
