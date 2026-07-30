import re

PHONE_REGEX = re.compile(
    r"^\+?[1-9]\d{1,14}$"
)

def validate_phone(phone: str) -> str:
    """Validate phone number format based on E.164 standard.
    
    Raises ValueError if format is invalid.
    """
    cleaned = re.sub(r"\s+", "", phone)
    if not PHONE_REGEX.match(cleaned):
        raise ValueError("Invalid phone number format. Must comply with E.164 standard.")
    return cleaned
