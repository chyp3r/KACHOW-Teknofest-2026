import re

PHONE_REGEX = re.compile(
    r"^\+?[1-9]\d{1,14}$"
)

def validate_phone(phone: str) -> str:
    """Telefon numarası biçimini E.164 standardına göre doğrular.

    Biçim geçersizse ValueError fırlatır.
    """
    cleaned = re.sub(r"\s+", "", phone)
    if not PHONE_REGEX.match(cleaned):
        raise ValueError("Invalid phone number format. Must comply with E.164 standard.")
    return cleaned
