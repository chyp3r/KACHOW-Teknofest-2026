"""Belge analizi için MCP-first mevzuat getirimi.

`mevzuat-mcp`'nin `search_mevzuat`'ı hem numara/başlık filtresini hem de
içerikte tam metin aramasını (`phrase`, Solr sözdizimi) destekler -- ama bu
modül bilinçli olarak yalnızca numaraya göre çözümleme kullanır (bkz.
`app.mcp.mevzuat_client.resolve_and_fetch`), *konu* bazlı canlı aramayı
değil. Sebep API sınırı değil, kapsam: burası yalnızca boot-zamanında
`CURATED_LEGISLATION`'ı ısıtan yol, `LOCAL_MODE`'dan bağımsız olarak her
zaman çalışır ve `retrieve()`'i asla ağ G/Ç yapmayan, tur-başına bedava bir
işlem olarak tutar (aşağıya bakın). İstek başına konu bazlı canlı arama
(`LOCAL_MODE=false` iken) `document_analysis_graph.retrieve_mevzuat_node`'da
ayrı, açıkça kapılı bir adımdır -- bu modülün sözleşmesini bozmadan.

`HybridRetriever` (Qdrant, dense+sparse) yerel yedek olarak kalır ve
`MEVZUAT_SOURCE="local"` iken tek kaynaktır.

Uyumluluğa (compliance) hiç dokunmaz. `check_required_fields`, sabit kodlu
madde numaralarına sahip bir kural tablosu üzerinde küme çıkarmadır; bu
modüldeki hiçbir şey o yol üzerinde değildir.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from langchain_core.documents import Document

from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.policy import get_policy
from app.ai.retrieval.bm25 import BM25Retriever
from app.core.config import settings
from app.mcp.mevzuat_client import resolve_and_fetch
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

#: Yerel bir literal yerine ChunkingPolicy.mevzuat_*'tan alınır --
#: scripts/index_mevzuat.py'nin yerel korpus için kullandığı parametrelerle
#: eşleşmelidir. Bunun nedeni iki indeksin doğrudan karşılaştırılması değil
#: (asla karşılaştırılmazlar; her kaynak bağımsız sıralanır), buradaki bir
#: uyumsuzluğun canlı yola, suggest_mevzuat'ın alıntı bütçesi ve prompt'unun
#: ayarlandığı granülariteden farklı pasajlar vermesidir. Bu çiftin Document
#: Q&A çiftinden neden ayrı tutulduğu için ChunkingPolicy'nin kendi
#: docstring'ine bakın.
CHUNK_SIZE = get_policy().chunking.mevzuat_chunk_size
CHUNK_OVERLAP = get_policy().chunking.mevzuat_chunk_overlap


@dataclass(frozen=True)
class _LegislationRef:
    """MCP üzerinden güncel tutulacak derlenmiş bir kanun.

    number/kind, scripts/fetch_mevzuat_corpus.py'nin CORPUS'unu birebir
    yansıtır (aynı derleme, her girdinin seçilme nedeni aynı -- bkz. o
    dosyanın docstring'i ve her girdinin `why` alanı). İçe aktarmak yerine
    tekrarlanmıştır: o betik repo kökünde yaşar ve tek seferlik dev-time
    getirimi için sys.path hack'iyle backend paketine erişir; ters yönde bir
    runtime modülü içe aktarmak, iki tekrar listeden daha büyük bir
    sınır-ötesi bağımlılık yaratırdı.
    """

    number: str
    kind: str
    title: str


CURATED_LEGISLATION: tuple[_LegislationRef, ...] = (
    _LegislationRef(
        "2646", "CB_YONETMELIK",
        "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
    ),
    _LegislationRef("3071", "KANUN", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    _LegislationRef("4982", "KANUN", "Bilgi Edinme Hakkı Kanunu"),
    _LegislationRef("657", "KANUN", "Devlet Memurları Kanunu"),
    _LegislationRef("6698", "KANUN", "Kişisel Verilerin Korunması Kanunu"),
    _LegislationRef("7201", "KANUN", "Tebligat Kanunu"),
    _LegislationRef("5070", "KANUN", "Elektronik İmza Kanunu"),
)


class McpMevzuatRetriever:
    """Canlı MCP getirimlerine dayanan, bellekte sıralanan mevzuat getirimi.

    `retrieve()` asla kendisi ağ G/Ç yapmaz -- yalnızca `warm_up()`'ın en son
    oluşturduğunu okur. Bu bilinçli bir tercihtir: `retrieve_mevzuat_node`,
    istek başına bir node bütçesi içinde çalışır (balanced'te 25s, fast'te
    15s -- bkz. `app.ai.policy.schema`), ve playwright tabanlı bir MCP
    sunucusu üzerinden yedi kanunun soğuk getirimi bu pencere içinde
    bitmesi garanti değildir. Getirimi tamamen istek yolunun dışında tutmak
    bunu varsayılan olarak güvenli kılar; `warm_up()`'ın, LLM istemcilerini
    ısıtan ve grafikleri derleyen aynı best-effort başlangıç yolundan bir kez
    await edilmesi amaçlanmıştır (bkz. `app.lifespan`).
    """

    def __init__(self) -> None:
        self._index: Optional[BM25Retriever] = None

    @property
    def is_warm(self) -> bool:
        """Şu anda kullanılabilir bir indeksin yüklü olup olmadığı."""
        return self._index is not None

    async def warm_up(self) -> None:
        """Derlenmiş her kanunu getir ve bellek içi indeksi (yeniden) oluştur.

        Kanun başına best-effort: bir kanunun çözümlenmesi veya getirilmesi
        başarısız olursa diğerlerini engellemez ve indeks başarılı olanlardan
        yeniden oluşturulur. Yalnızca tam bir başarısızlık (sıfır kanun
        getirildi) indeksi boş bırakır -- bu durumda `retrieve()` warm
        olmadığını bildirir ve çağıran yerel korpusa döner.
        """
        if not is_registered(MEVZUAT_SERVER):
            logger.info(
                "Mevzuat MCP server is not registered; MCP-first retrieval "
                "will stay on the local corpus."
            )
            return

        results = await asyncio.gather(
            *(self._fetch_one(ref) for ref in CURATED_LEGISLATION),
            return_exceptions=True,
        )

        chunker = RecursiveChunker(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks: list[Document] = []
        failures = 0
        for ref, result in zip(CURATED_LEGISLATION, results):
            if isinstance(result, BaseException):
                failures += 1
                logger.warning(
                    "MCP fetch failed for %s (%s): %s", ref.number, ref.title, result
                )
                continue
            document_id, text = result
            law_chunks = await chunker.split_text(text)
            for chunk in law_chunks:
                chunk.metadata = {
                    **chunk.metadata,
                    "mevzuat": ref.title,
                    "source": f"mcp:{document_id}",
                }
            chunks.extend(law_chunks)

        if not chunks:
            logger.warning(
                "MCP-first legislation warm-up fetched nothing (%d/%d laws "
                "failed); staying on the local corpus until the next warm-up.",
                failures,
                len(CURATED_LEGISLATION),
            )
            return

        index = BM25Retriever()
        index.index_documents(chunks)
        self._index = index
        logger.info(
            "MCP-first legislation index warm: %d chunk(s) from %d/%d law(s).",
            len(chunks),
            len(CURATED_LEGISLATION) - failures,
            len(CURATED_LEGISLATION),
        )

    async def _fetch_one(self, ref: _LegislationRef) -> tuple[str, str]:
        """Derlenmiş bir kanunu çözümle ve getir, herhangi bir hatada fırlat.

        Asistanın canlı aracının kullandığı aynı arama başına zaman aşımıyla
        sınırlıdır: yedi kanunun tamamı eş zamanlı getirilir, bu sınır
        olmadan takılı kalan tek bir çağrı, diğer altısının sonuçlarını,
        asyncio.gather'ın fark etmesi ne kadar sürerse (tüm başlangıç
        warm-up bütçesine kadar) o kadar rehin tutardı; olağan tekli-arama
        sınırı yerine.

        Raises:
            RuntimeError: Kanun çözümlenemediğinde veya getirilemediğinde.
            asyncio.TimeoutError: Zamanında bitmediğinde.
        """
        resolved = await asyncio.wait_for(
            resolve_and_fetch(ref.number, ref.kind),
            timeout=settings.MEVZUAT_MCP_TIMEOUT_SECONDS,
        )
        if resolved is None:
            raise RuntimeError(f"{ref.number} ({ref.title}) resolved to nothing")
        return resolved

    async def retrieve(self, query: str, limit: int = 5) -> list[Document]:
        """Warm bellek içi indeksi bir sorguya göre sırala.

        Args:
            query: Arama sorgusu (yerel retriever'ın alacağı aynı
                deterministik dize).
            limit: Döndürülecek maksimum belge sayısı.

        Returns:
            Sıralanmış alıntılar, veya henüz hiçbir indeks warm değilse
            boş liste -- asla ağ G/Ç yapmaz.
        """
        if self._index is None:
            return []
        return await self._index.retrieve(query, limit)


class FallbackMevzuatRetriever:
    """Önce bir birincil retriever'ı dener, hata veya boşluk durumunda ikincile döner.

    `HybridRetriever`'ın `async retrieve(query, limit) -> list[Document]`
    arayüzünü duck-type eder, bu yüzden `retrieve_mevzuat_node`'un hangi
    kaynağı kullanacağına dair hiçbir değişikliğe ihtiyacı yoktur -- strateji
    tamamen burada, dependency-injection sınırında yaşar (bkz.
    `app.api.dependency.get_mevzuat_retriever`).

    Sadece bir istisna değil, boş bir *başarılı* birincil sonuç da ikincile
    düşer: MCP-first, yerel korpusun sahip olduğu aynı derlenmiş kanun
    kümesini yalnızca BM25 üzerinden sıralar (dense yarı yoktur, çünkü
    istek zamanında bir embedding indeksi oluşturmak ağ yolunun dışında
    kalma amacını boşa çıkarırdı) -- bu yüzden yerel retriever'ın dense
    yarısının yakalayacağı bir sorgu, tam olarak bu düşüşün en çok
    yardımcı olduğu yerdir.
    """

    def __init__(self, primary, fallback) -> None:
        self._primary = primary
        self._fallback = fallback

    async def retrieve(self, query: str, limit: int = 5) -> list[Document]:
        try:
            documents = await self._primary.retrieve(query, limit)
        except Exception:
            logger.warning("MCP-first legislation retrieval failed; falling back to local corpus.", exc_info=True)
            documents = []

        if documents:
            return documents
        return await self._fallback.retrieve(query, limit)

    async def warm_up(self) -> None:
        """Varsa, birincilin warm-up'ına best-effort geçiş."""
        warm_up = getattr(self._primary, "warm_up", None)
        if warm_up is None:
            return
        try:
            await warm_up()
        except Exception:
            logger.warning("MCP-first legislation warm-up failed; staying on local corpus.", exc_info=True)
