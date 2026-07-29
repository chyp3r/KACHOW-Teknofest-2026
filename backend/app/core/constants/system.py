"""Sistem geneli sabitler.

Uygulama boyunca paylaşılan, değişmeyen değerleri barındırır.
Konfigürasyona bağlı değişkenler için core/config.py kullanılmalıdır.
"""

# ---------- Dosya Yükleme ----------
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024  # 50 MB
ALLOWED_FILE_TYPES: list[str] = ["application/pdf", "text/plain", "application/msword"]

# ---------- Sayfalama ----------
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# ---------- AI İş Akışı ----------
MAX_RETRY_ATTEMPTS: int = 3
AI_WORKFLOW_TIMEOUT_SECONDS: int = 120

# ---------- CORS ----------
CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# ---------- Cache ----------
CACHE_TTL_SECONDS: int = 60 * 60  # 1 saat
