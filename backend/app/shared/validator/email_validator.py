import re

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

def validate_email(email: str) -> str:
    """E-posta adresi biçimini doğrular.

    Biçim geçersizse ValueError fırlatır.
    """
    if not EMAIL_REGEX.match(email):
        raise ValueError("Invalid email format.")
    return email
