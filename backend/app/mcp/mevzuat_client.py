"""Bir mevzuat numarasını güncel resmi metnine çözümleyen her çağıran
tarafından paylaşılan düşük seviyeli mevzuat-mcp işlemleri.

`app.ai.tools.mevzuat_tools` (asistanın canlı arama aracı) içinden ayrı bir
modüle çıkarıldı; `app.ai.retrieval.mcp_mevzuat` (doküman analizinin
MCP-öncelikli getiricisi) için tekrar yazılmadı: ikisi de tam olarak aynı iki
şeye ihtiyaç duyar -- bir `mevzuat_no`'yu, mülga edilmiş eş kaydı atlayarak bir
doküman kimliğine çözümlemek, ardından o kimliğin tam metnini getirmek --
ve mülga işareti tuzağı, tek bir uygulamaya sahip olmayı gerektirecek kadar
inceliklidir.

Kendi zaman aşımı politikasını taşımaz. Her çağıranın uygulaması gereken
kendi sınırı zaten vardır (asistan tek bir aramayı `MEVZUAT_MCP_TIMEOUT_SECONDS`
içine sarar; getirici ise kanun başına eşzamanlı çok sayıda getirmeyi farklı
şekilde sınırlar), bu yüzden `asyncio.wait_for` burada tekrarlanmak yerine
çağrı noktasına aittir.
"""

import logging
import re
from typing import Optional

from app.mcp.manager import mcp_manager
from app.mcp.registry import MEVZUAT_SERVER

logger = logging.getLogger(__name__)

#: Artık yürürlükte olmayan mevzuat için sonuç satırı işaretleri. Bir kanunun
#: mülga edilmiş eş kaydı, kanunun kendisiyle *aynı* numarayı taşır; bu yüzden
#: yalnızca numara eşleştirmesi bunları ayırt edemez.
_REPEALED_MARKERS = ("Mülga", "MÜLGA", "YÜRÜRLÜKTEN KALDIRILMIŞ")


def text_of(result: object) -> str:
    """Bir MCP araç sonucundan metin içeriğini oku.

    Args:
        result: `MCPManager.call_tool` tarafından döndürülen her ne ise.

    Returns:
        İlk metin içerik bloğu, ya da boş bir dize.
    """
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def pick_document_id(search_output: str) -> Optional[str]:
    """Bir arama yanıtından en iyi sonucun doküman kimliğini seç.

    Sunucu, ``- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: 102924``
    gibi Markdown benzeri satırlar döndürür.

    İlk `mevzuatId`'yi almak yanlıştır, hem de sessizce yanlıştır. 657 için
    arama yapmak, gerçek Devlet Memurları Kanunu'ndan (102924) *önce*
    "DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ"ni
    (mevzuat_id 335559) döndürür -- ikisi de meşru şekilde 657 numaralı,
    biri mülga edilmiş. Mülga edilmiş metni güncel kanun diye alıntılamak, bu
    projenin varoluş amacının tam olarak önlemeye çalıştığı hatadır; bu yüzden
    mülga kayıtlar atlanır ve yalnızca başka hiçbir şey eşleşmediğinde
    yedek olarak kullanılır.

    Args:
        search_output: Bir `search_mevzuat` yanıtının ham metni.

    Returns:
        Seçilen doküman kimliği, ya da yanıtın hiç sonucu yoksa None.
    """
    fallback: Optional[str] = None
    for line in search_output.splitlines():
        match = re.search(r"mevzuatId:\s*(\d+)", line)
        if not match:
            continue
        if any(marker in line for marker in _REPEALED_MARKERS):
            fallback = fallback or match.group(1)
            continue
        return match.group(1)
    return fallback


async def resolve_mevzuat_id(mevzuat_no: str, mevzuat_tur: Optional[str] = None) -> Optional[str]:
    """Bir mevzuat numarasını güncel doküman kimliğine çözümle.

    Önce verilen tür filtresini dener (daha ucuzdur ve çoğu numara için
    mülga edilmiş eş kaydı doğrudan dışlar), ardından vazgeçmeden önce
    filtresiz olarak tekrar dener -- numaralı bir yönetmelik, tüzük veya KHK,
    yalnızca KANUN filtresi altında eşleşmez ve bu projenin kendi araç
    açıklamaları, sayısal bir sorgunun bir tanesini aramanın güvenilir yolu
    olduğunu vaat eder.

    Args:
        mevzuat_no: Resmi mevzuat numarası.
        mevzuat_tur: Önce denenecek tür filtresi (örn. "KANUN"), ya da
            baştan filtresiz aramak için None.

    Returns:
        Çözümlenen doküman kimliği, ya da numarayla hiçbir şey eşleşmezse
        None.
    """
    if mevzuat_tur:
        filtered = await mcp_manager.call_tool(
            MEVZUAT_SERVER,
            "search_mevzuat",
            {"mevzuat_no": mevzuat_no, "mevzuat_tur": mevzuat_tur, "page_size": 5},
        )
        document_id = pick_document_id(text_of(filtered))
        if document_id is not None:
            return document_id

    unfiltered = await mcp_manager.call_tool(
        MEVZUAT_SERVER, "search_mevzuat", {"mevzuat_no": mevzuat_no, "page_size": 5}
    )
    return pick_document_id(text_of(unfiltered))


async def fetch_mevzuat_text(mevzuat_id: str) -> str:
    """Bir kanunun tam güncel metnini doküman kimliğine göre getir.

    Args:
        mevzuat_id: `resolve_mevzuat_id` tarafından çözümlenen doküman kimliği.

    Returns:
        Tam metin, ya da sunucu hiçbir şey döndürmediyse boş bir dize.
    """
    content = await mcp_manager.call_tool(
        MEVZUAT_SERVER, "get_mevzuat_content", {"mevzuat_id": mevzuat_id}
    )
    return text_of(content).strip()


async def resolve_and_fetch(
    mevzuat_no: str, mevzuat_tur: Optional[str] = None
) -> Optional[tuple[str, str]]:
    """Bir mevzuat numarasını çözümle ve güncel tam metnini getir.

    Args:
        mevzuat_no: Resmi mevzuat numarası.
        mevzuat_tur: Önce denenecek tür filtresi, ya da filtresiz aramak
            için None.

    Returns:
        Doküman kimliği ve metni, ya da çözümleme veya getirme hiçbir şey
        bulamazsa None.
    """
    document_id = await resolve_mevzuat_id(mevzuat_no, mevzuat_tur)
    if document_id is None:
        return None
    text = await fetch_mevzuat_text(document_id)
    if not text:
        return None
    return document_id, text


async def search_by_phrase(query: str, page_size: int = 5) -> Optional[str]:
    """Bir konu/soru string'iyle mevzuat.gov.tr'de tam metin araması yap.

    `resolve_mevzuat_id`'nin numaraya göre araması yalnızca `mevzuat_no`
    filtresini kullanıyordu, bu yüzden bir başlık dışı konu sorgusuyla hiç
    işe yaramazdı. Bu fonksiyon farklı bir parametre setini kullanır:
    `phrase` (içerikte tam metin arama, Solr sözdizimi) ve
    `basliktaAra=False` -- sunucu `basliktaAra` için varsayılan olarak
    `True` kullanır (yalnızca başlıkta arar), bu yüzden açıkça `False`
    verilmezse bir konu sorgusu neredeyse hiçbir zaman eşleşmez.

    Args:
        query: Anahtar kelime yoğun bir konu/soru string'i (örn.
            `_build_mevzuat_query`'nin ürettiği).
        page_size: İstenecek sonuç sayısı.

    Returns:
        En iyi eşleşen mevzuatın doküman kimliği, ya da hiçbir şey
        eşleşmezse None.
    """
    result = await mcp_manager.call_tool(
        MEVZUAT_SERVER,
        "search_mevzuat",
        {"phrase": query, "basliktaAra": False, "page_size": page_size},
    )
    return pick_document_id(text_of(result))


async def excerpt_within(
    mevzuat_id: str, keyword: str, max_results: int = 5
) -> str:
    """Bir mevzuatın içinden, sorguyla eşleşen pasajları getir.

    Tam metni çekip sabit bir karakter sayısına kırpmak (`fetch_mevzuat_text`
    + kırpma) uzun bir kanunda (657 gibi ~500k karakter) neredeyse her zaman
    ilgili maddeyi değil, başlangıç hükümlerini döndürür. Bu, sunucunun
    kendi içerik-içi arama aracını kullanarak gerçekten ilgili pasajı hedefler.

    Args:
        mevzuat_id: `search_by_phrase` tarafından çözümlenen doküman kimliği.
        keyword: İçeride aranacak sorgu.
        max_results: Döndürülecek maksimum pasaj sayısı.

    Returns:
        Eşleşen pasajlar, ya da hiçbiri yoksa boş bir dize.
    """
    result = await mcp_manager.call_tool(
        MEVZUAT_SERVER,
        "search_within_mevzuat",
        {"mevzuat_id": mevzuat_id, "keyword": keyword, "max_results": max_results},
    )
    return text_of(result).strip()


async def search_and_excerpt(
    query: str, max_results: int = 5
) -> Optional[tuple[str, str]]:
    """Bir konu sorgusunu mevzuata çözümle, sonra içinden hedefli alıntı çek.

    `resolve_and_fetch`'in konu-sorgusu eşdeğeri: `search_by_phrase` +
    `excerpt_within`'i zincirler (2 MCP round-trip, `resolve_and_fetch`'in
    en kötü durumdaki 3'ünden az). Eşleşen mevzuat bulunsa bile içinde
    sorguyla örtüşen bir pasaj yoksa None döner -- tam metne düşmek, bu
    fonksiyonun var olma nedenini (hedefli alıntı) geçersiz kılardı.

    Args:
        query: Anahtar kelime yoğun bir konu/soru string'i.
        max_results: `excerpt_within`'e iletilen pasaj sınırı.

    Returns:
        Doküman kimliği ve eşleşen pasajlar, ya da hiçbir eşleşme yoksa None.
    """
    document_id = await search_by_phrase(query)
    if document_id is None:
        return None
    excerpt = await excerpt_within(document_id, query, max_results)
    if not excerpt:
        return None
    return document_id, excerpt
