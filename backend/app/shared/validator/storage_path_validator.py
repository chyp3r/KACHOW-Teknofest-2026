import os
import re

from app.core.config import settings

#: DocumentService._store()'un ürettiği tam biçimle eşleşir:
#: f"{UPLOAD_PATH_PREFIX}/{uuid4().hex}{extension}" -- "uploads/<32 hex><.ext>".
_STORAGE_PATH_PATTERN = re.compile(r"^uploads/[0-9a-f]{32}\.[A-Za-z0-9]{1,10}$")


def validate_storage_path(value: str) -> str:
    """Bir storage_path'in iyi biçimli, dizin gezinmesine izin vermeyen bir yükleme anahtarı olduğunu doğrular.

    İstemcinin gönderdiği ``storage_path``, kimlik doğrulaması gerektirmeyen
    bir uç noktada, yerel backend için dosya sistemiyle arasında başka hiçbir
    engel olmadan ``storage.get_file(...)``'a ulaşır -- buradaki gevşek bir
    kontrol bir biçimsellik değil, path-traversal (dizin gezinmesi) okuma
    ilkelidir.

    Args:
        value: İstemcinin gönderdiği storage_path.

    Returns:
        Doğrulanmış değer, değiştirilmeden.

    Raises:
        ValueError: Değer ``_store()``'un ürettiği biçimle eşleşmiyorsa
            veya (yerel backend için) depolama dizini dışına çözümleniyorsa.
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
