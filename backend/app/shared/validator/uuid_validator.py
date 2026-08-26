import uuid

def validate_uuid(value: str) -> str:
    """Verilen değerin geçerli bir UUID versiyon 4 olduğunu doğrular.

    Biçim geçersizse ValueError fırlatır.
    """
    try:
        val = uuid.UUID(value, version=4)
        return str(val)
    except ValueError:
        raise ValueError("Invalid UUID version 4.")
