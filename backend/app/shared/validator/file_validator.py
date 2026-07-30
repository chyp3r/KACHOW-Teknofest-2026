from typing import List

def validate_file_extension(filename: str, allowed_extensions: List[str]) -> bool:
    """Check if the file extension is within the allowed list.
    
    Returns True if allowed, False otherwise.
    """
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in [e.lower().lstrip(".") for e in allowed_extensions]
