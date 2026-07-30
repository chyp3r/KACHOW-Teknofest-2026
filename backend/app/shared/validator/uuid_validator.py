import uuid

def validate_uuid(value: str) -> str:
    """Validate that value string is a valid UUID version 4.
    
    Raises ValueError if format is invalid.
    """
    try:
        val = uuid.UUID(value, version=4)
        return str(val)
    except ValueError:
        raise ValueError("Invalid UUID version 4.")
