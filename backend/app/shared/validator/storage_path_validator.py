import os
import re

from app.core.config import settings

#: Matches exactly what DocumentService._store() produces:
#: f"{UPLOAD_PATH_PREFIX}/{uuid4().hex}{extension}" -- "uploads/<32 hex><.ext>".
_STORAGE_PATH_PATTERN = re.compile(r"^uploads/[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$")


def validate_storage_path(value: str) -> str:
    """Validate a storage_path is a well-formed, non-traversing upload key.

    A client-supplied ``storage_path`` reaches ``storage.get_file(...)`` on an
    unauthenticated endpoint with nothing else standing between it and the
    filesystem for the local backend -- a permissive check here is a
    path-traversal read primitive, not a formality.

    Args:
        value: The client-supplied storage_path.

    Returns:
        The validated value, unchanged.

    Raises:
        ValueError: If the value doesn't match the shape ``_store()`` produces,
            or (for the local backend) resolves outside the storage directory.
    """
    if not value or "\x00" in value or ".." in value or value.startswith("/"):
        raise ValueError("Geçersiz storage_path.")
    if not _STORAGE_PATH_PATTERN.match(value):
        raise ValueError("storage_path beklenen biçimde değil (uploads/<uuid><uzantı>).")

    if settings.STORAGE_TYPE == "local":
        base = os.path.realpath(settings.LOCAL_STORAGE_DIR)
        candidate = os.path.realpath(os.path.join(base, value))
        if not (candidate == base or candidate.startswith(base + os.sep)):
            raise ValueError("storage_path depolama dizini dışına çıkıyor.")

    return value
