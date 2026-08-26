"""Asistan için MCP üzerinden canlı mevzuat sorgusu.

`datasets/mevzuat/` altındaki commit'lenmiş korpus yedi kanun tutar ve
hiç ağ kullanmadan puanlanan her gerekliliği yanıtlar. Diğer birkaç bin
tanesi hakkında bir soruyu yanıtlayamaz; bu, tam olarak bunun için var:
korpusun kapsamadığı bir soru, kendinden emin yanlış bir yanıt almak veya
düz bir "bulunamadı" yerine mevzuat.gov.tr'ye ulaşır.

Üç özellik, hepsi bilinçli:

* **Yalnızca eklemeli.** Bu, hiçbir zaman bir uygunluk kararını kilitlemez.
  `check_required_fields`, sabit kodlanmış madde numaralarıyla bir kural
  tablosu üzerinde küme çıkarmasıdır ve analiz pipeline'ı bu modülü asla
  çağırmaz -- aynı evrakın her çalıştırmada bayt bayt aynı çıktıyı
  üretmesini sağlayan şey budur.
* **İkinci, birinci değil.** `search_legislation` (yerel korpus) bundan önce
  kaydedilir, bu yüzden model varsayılan olarak çevrimdışı yola başvurur ve
  bu, onun eskalasyonudur.
* **Başarısızlık bir yanıttır.** Erişilemeyen bir devlet sitesi, yerel
  aracın döndürdüğü aynı "bulunamadı" string'ini döndürür, asla bir hata
  fırlatmaz. Bir sohbet turu, üçüncü taraf bir site çalışmadığı için 500
  vermemelidir ve araç açıklaması modele sonucun onu vaat etmek yerine
  *var olduğunda* yetkili olduğunu söyler.
"""

import asyncio
import logging

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec
from app.core.config import settings
from app.mcp.manager import mcp_manager
from app.mcp.mevzuat_client import fetch_mevzuat_text, pick_document_id, resolve_and_fetch, text_of
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

NOT_FOUND = "İlgili bir mevzuat maddesi bulunamadı."

#: Modele geri verilen mevzuat metninin karakter sayısı. Bütün bir kanun yarım
#: milyon karaktere kadar çıkabilir (657 çıkıyor), bu bağlam penceresini şişirir.
EXCERPT_CHAR_LIMIT = 6000


class SearchLiveLegislationArgs(BaseModel):
    """Arguments for the ``search_legislation_live`` tool."""

    query: str = Field(
        description=(
            "Aranacak mevzuatın adı veya numarası (örn. '657', "
            "'Tebligat Kanunu'). Konu değil, mevzuatın kendisi aranır."
        )
    )


async def _lookup(query: str) -> str:
    """Bir mevzuat adını veya numarasını resmî metnine çözümler.

    Args:
        query: Mevzuat adı veya numarası.

    Returns:
        Resmî metnin bir alıntısı, veya `NOT_FOUND`.
    """
    # Sayısal sorgular güvenilir yoldur. Başlığa göre çözümleme, önemli
    # olacak kadar sık yanlış belge döndürür -- "Devlet Memurları Kanunu"
    # araması, 657'yi *değiştiren* 2022 tarihli bir kanun olan 7417'yi en
    # üste koyar; 657'nin kendisi ise hiç görünmez. `scripts/
    # fetch_mevzuat_corpus.py`'nin belgelediği aynı tuzak.
    stripped = query.strip()
    if stripped.isdigit():
        # Önce KANUN (daha ucuz ve 657'nin yürürlükten kaldırılmış eşini
        # doğrudan dışlayan şey), vazgeçmeden önce filtresiz yeniden dener --
        # bu aracın kendi açıklaması "kanun veya yönetmeliğin" vaat eder ve
        # modele sayısal bir sorgunun güvenilir olan olduğunu söyler, bu
        # yüzden numaralı bir yönetmelik, tüzük veya KHK, yalnızca ilk
        # deneme sadece KANUN istediği için burada çıkmaza girmemelidir.
        # resolve_and_fetch ve app.ai.retrieval.mcp_mevzuat'taki retriever
        # tam olarak bu çözümleme mantığını paylaşır.
        resolved = await resolve_and_fetch(stripped, "KANUN")
    else:
        by_name = await mcp_manager.call_tool(
            MEVZUAT_SERVER, "search_mevzuat", {"mevzuat_adi": stripped, "page_size": 5}
        )
        document_id = pick_document_id(text_of(by_name))
        resolved = None
        if document_id is not None:
            text = await fetch_mevzuat_text(document_id)
            resolved = (document_id, text) if text else None

    if resolved is None:
        return NOT_FOUND
    document_id, text = resolved

    if len(text) > EXCERPT_CHAR_LIMIT:
        text = text[:EXCERPT_CHAR_LIMIT] + "\n\n[... metin kısaltıldı ...]"
    return f"(Kaynak: mevzuat.gov.tr, mevzuat_id={document_id})\n\n{text}"


def build_live_legislation_tools() -> list[ToolSpec]:
    """MCP sunucusu yapılandırıldığında canlı mevzuat aracını inşa eder.

    Returns:
        `MEVZUAT_MCP_ENABLED` açık ve sunucu kayıtlıysa tek elemanlı bir
        liste, aksi halde boş bir liste -- böylece modele asla çalışamayacak
        bir araç sunulmaz.
    """
    # Yalnızca kayıt değil, her iki koşul da: bugün `register_servers()`,
    # `mcp_manager.register_server`'ın tek çağıranıdır ve zaten bu aynı
    # bayrağa göre kapılanır, bu yüzden yalnızca is_registered()'ı kontrol
    # etmek tesadüfen bayrakla uyuşur. Burada ikisini de doğrudan kontrol
    # etmek, bunun eklenen tek kayıt yolu olduğu gerçeğine bağımlılığı
    # ortadan kaldırır; bu gerçeği gelecekteki bir çağıranın sessizce
    # geçersiz kılabileceği bir gerçek olarak bırakmak yerine.
    if not settings.MEVZUAT_MCP_ENABLED or not is_registered(MEVZUAT_SERVER):
        return []

    async def _search_legislation_live(query: str) -> str:
        try:
            return await asyncio.wait_for(
                _lookup(query), timeout=settings.MEVZUAT_MCP_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Live legislation lookup timed out after %ss for %r.",
                settings.MEVZUAT_MCP_TIMEOUT_SECONDS,
                query,
            )
            return NOT_FOUND
        except Exception:
            # Yerel aracın hata durumunda döndürdüğü aynı string'e düşer:
            # erişilemeyen bir devlet sitesi bozuk bir sohbet değil, "sonuç
            # yok" demektir.
            logger.exception("Live legislation lookup failed for %r.", query)
            return NOT_FOUND

    return [
        ToolSpec(
            name="search_legislation_live",
            description=(
                "Resmî mevzuat veritabanından (mevzuat.gov.tr) bir kanun veya "
                "yönetmeliğin güncel tam metnini getirir. Yalnızca "
                "search_legislation yerel korpusta yanıt bulamadığında kullan; "
                "mevzuatı numarasıyla aramak (örn. '657') adıyla aramaktan daha "
                "güvenilirdir."
            ),
            args_schema=SearchLiveLegislationArgs,
            handler=_search_legislation_live,
        )
    ]
