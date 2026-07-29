from app.core.config import settings
from app.infrastructure.storage.base import BaseStorage
from app.infrastructure.storage.local import LocalStorage
from app.infrastructure.storage.s3 import S3Storage

# Lazy singleton storage instance
_storage_client = None


def get_storage_client() -> BaseStorage:
    """Retrieve the global configured storage client (Local or S3/MinIO)."""
    global _storage_client
    if _storage_client is None:
        storage_type = settings.STORAGE_TYPE.lower()
        if storage_type == "s3":
            _storage_client = S3Storage(
                bucket_name=settings.S3_BUCKET_NAME,
                endpoint_url=settings.S3_ENDPOINT_URL,
                access_key=settings.S3_ACCESS_KEY,
                secret_key=settings.S3_SECRET_KEY,
            )
        else:
            _storage_client = LocalStorage(base_dir=settings.LOCAL_STORAGE_DIR)
    return _storage_client


__all__ = ["BaseStorage", "LocalStorage", "S3Storage", "get_storage_client"]
