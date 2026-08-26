"""Planlama grafiği için bir belgenin analiz önbelleğine okuma-tarafı erişim.

Doğrudan `app.ai`'dan okumak yerine `app.domains.documents` içinde
tutuluyor: `app.ai.workflows.planning_graph` hiçbir zaman `app.domains`'i
import etmez (bkz. `docs/architecture/backend.md` ve bunun statik
uygulamasını yapan `backend/tests/unit/ai/
test_ai_never_imports_domains.py`), bu yüzden bu, `units_provider`/
`adapter_provider`'ın zaten yaptığı gibi, inşa anında grafiğe düz bir
çağrılabilir (callable) olarak veriliyor.
"""

import json
import logging

from app.domains.documents.cache_keys import analysis_cache_key
from app.infrastructure.storage import get_storage_client

logger = logging.getLogger(__name__)


async def get_cached_document(document_id: str) -> dict:
    """Planlama grafiği için önceden analiz edilmiş bir belgenin önbelleğini oku.

    `get_storage_client()` üzerinden okur -- bir belgenin kendi byte'larının
    ve analiz önbelleğinin yaşadığı aynı backend (bkz.
    `app.domains.documents.service._save_document_analysis_cache`) -- ham
    bir yerel-dosya-sistemi yolu değil. Herhangi bir hatada (eksik anahtar,
    okunamayan JSON, bir depolama backend kesintisi) boş bir dict'e düşer:
    eksik bir önbellek normal, sık karşılaşılan bir durumdur (kullanıcı
    bir belgeye önceki bir yükleme yerine isimle atıfta bulunuyor), tüm
    planlama adımını başarısız kılmaya değecek bir hata değildir.

    Args:
        document_id: Belgenin depolama yolu.

    Returns:
        Önbellek payload'ı (`extracted_text`/`pages`/`analysis` anahtarları --
        bkz. `_save_document_analysis_cache`), ya da yüklenecek bir şey
        yoksa veya okuma/ayrıştırma herhangi bir nedenle başarısız olursa
        `{}`.
    """
    try:
        content = await get_storage_client().get_file(analysis_cache_key(document_id))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}

    try:
        return json.loads(content)
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}
