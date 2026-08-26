import math
import re
from typing import List, Optional

from langchain_core.documents import Document

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient


def cosine_distance(u: List[float], v: List[float]) -> float:
    """İki vektör arasındaki kosinüs mesafesini hesaplar."""
    dot_product = sum(a * b for a, b in zip(u, v))
    norm_u = math.sqrt(sum(a * a for a in u))
    norm_v = math.sqrt(sum(b * b for b in v))
    if norm_u == 0 or norm_v == 0:
        return 1.0
    similarity = dot_product / (norm_u * norm_v)
    # Kayan nokta sorunlarının benzerliği [-1, 1] aralığının dışına taşırmasını önlemek için kırp
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


class SemanticChunker(BaseChunker):
    """Metni karakter uzunlukları yerine ardışık cümleler arasındaki anlamsal
    benzerlik/mesafeye göre böler.

    PRODUKSİYONA BAĞLANMAMIŞTIR -- ve olduğu haliyle bağlanmamalıdır. Herhangi
    bir prodüksiyon çağrı noktasının kullandığı tek chunker ``RecursiveChunker``
    (``app.ai.embeddings.chunking.recursive``) sınıfıdır; ``ChunkingPolicy``
    (``app.ai.policy.schema``) kasıtlı olarak bu sınıfı seçen bir strateji
    alanı taşımaz. Bu "bağlamayı tamamlamayı unutmuş" bir durum değildir --
    bugün ``DocumentService._index_for_qa`` içine takmayı güvensiz kılan üç
    somut sorun vardır:

    1. ``start_index`` metadata'sı yok. ``_index_for_qa``, bir parçanın
       sayfasını ``app.ai.documents.anchors.build_page_map`` üzerinden
       bulmak için ``start_index``'ini okur ve ``RecursiveChunker`` bunu
       ``RecursiveCharacterTextSplitter(add_start_index=True)`` ile sağlar.
       Bu sınıf ise yalnızca ``chunk_index``/``sentence_count`` üretir.
       Olduğu gibi eklemek yalnızca ``[s. N]`` sayfa alıntısını düşürmekle
       kalmaz -- gelecekte bir değişiklik gruplanmış cümleleri
       ``" ".join(...)`` ile birleştirip saf bir yeniden-arama işlemini
       ofset olarak ele alırsa, bu durum
       ``app.ai.documents.anchors.PAGE_SEPARATOR``'ı (``"\\n\\n"``) tek bir
       boşluğa indirger; böylece birleştirilmiş dizeden hesaplanan herhangi
       bir ofset, ``build_page_map``'in sayfa sınırlarını bulmak için
       kullandığı miktar kadar kayar -- alıntı sadece eksik değil,
       *yanlış* olur ki bu daha kötüdür.
    2. ``_split_into_sentences``'ın regex'i Türkçe resmi yazışmalar için
       güvenli değildir. Negatif lookbehind ``(?<![A-Z][a-z]\\.)`` yalnızca
       ASCII büyük harfleri tanır, dolayısıyla ``İ/Ş/Ğ/Ç/Ö/Ü`` kullanan
       Türkçe kısaltma kalıplarını korumaz; ayrıca bu belge türünün dolu
       olduğu yaygın Türkçe kısaltmalar ("Sn.", "Dr.", "T.C.", "vb.",
       "md.") veya numaralı madde işaretleri ("1.", "2.") için bir istisna
       listesi de yoktur -- her biri sahte bir cümle sınırıdır.
    3. Maksimum parça boyutu ve örtüşme yoktur. Uzun, konu bakımından
       homojen bir belge (resmi yazışmalar çoğunlukla böyledir), kısaltmak
       yerine ``DraftPolicy.source_chunk_char_budget``'ın tamamen
       düşüreceği tek, çok büyük bir parça üretebilir ve
       ``RecursiveChunker``'ın yapılandırılmış örtüşmesinin yaptığı gibi
       bir parça sınırına denk gelen bir yanıtı kurtaracak örtüşme yoktur.

    Bu sınıf, yalnızca değerlendirme amaçlı bir keşif kolu olarak (bkz.
    ``evaluation``'ın retrieval paketi) pakette dışa aktarılmış ve birim
    testli olarak kalır -- bu belge türünde ``RecursiveChunker``'ı geçip
    geçmediği ölçülmesi gereken bir soru olup henüz karara bağlanmamıştır
    ve cevabı bir docstring'e değil bir rapora aittir.
    Yukarıdaki (1)-(3) maddelerini önce düzeltmeden ve geçişi
    gerekçelendirecek değerlendirme sayıları olmadan bunu
    ``DocumentService`` içine bağlamayın.
    """

    def __init__(
        self,
        embeddings_client: BaseEmbeddingsClient,
        threshold_type: str = "percentile",
        threshold_value: float = 85.0,
        min_sentences: int = 1,
    ):
        """Semantic Chunker'ı başlatır.

        Args:
            embeddings_client: Cümle vektörleri üretmek için bir BaseEmbeddingsClient örneği.
            threshold_type: Kullanılacak eşikleme türü. Seçenekler: "percentile", "static".
            threshold_value: Yüzdelik değer (0-100) veya sabit mesafe eşiği (0.0-1.0).
            min_sentences: Bir parçada tutulacak minimum cümle sayısı.
        """
        self.embeddings_client = embeddings_client
        self.threshold_type = threshold_type.lower()
        self.threshold_value = threshold_value
        self.min_sentences = min_sentences

    def _split_into_sentences(self, text: str) -> List[str]:
        """Metni bir regex kalıbı kullanarak cümlelere böler."""
        # Cümle sınırlarına göre böl: nokta, soru işareti, ünlem işareti ve ardından boşluk.
        sentence_ends = re.compile(r"(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s")
        sentences = sentence_ends.split(text)
        return [s.strip() for s in sentences if s.strip()]

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Metni cümle embedding'lerini kullanarak anlamsal olarak böler."""
        sentences = self._split_into_sentences(text)

        if not sentences:
            return []
        if len(sentences) <= self.min_sentences:
            return [Document(page_content=text, metadata={"chunk_index": 0})]

        # 1. Tüm cümleler için embedding üret
        embeddings = await self.embeddings_client.embed_documents(sentences)

        # 2. Ardışık cümleler arasındaki kosinüs mesafelerini hesapla
        distances = []
        for i in range(len(embeddings) - 1):
            dist = cosine_distance(embeddings[i], embeddings[i + 1])
            distances.append(dist)

        # 3. Bölme için mesafe eşiğini belirle
        if self.threshold_type == "percentile":
            if not distances:
                threshold = 0.5
            else:
                sorted_dists = sorted(distances)
                # Yüzdelik ile eşleşen indeksi bul
                pct_index = int((self.threshold_value / 100.0) * len(distances))
                pct_index = max(0, min(pct_index, len(distances) - 1))
                threshold = sorted_dists[pct_index]
        else:
            threshold = self.threshold_value

        # 4. Bölmelere göre cümleleri grupla
        chunks = []
        current_chunk_sentences = [sentences[0]]

        for i in range(len(distances)):
            next_sentence = sentences[i + 1]
            dist = distances[i]

            # Mesafe eşiği aşarsa yeni bir parça başlat
            if dist > threshold and len(current_chunk_sentences) >= self.min_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = [next_sentence]
            else:
                current_chunk_sentences.append(next_sentence)

        if current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))

        # 5. Belge listesini döndür
        return [
            Document(
                page_content=chunk_text,
                metadata={
                    "chunk_index": idx,
                    "sentence_count": len(self._split_into_sentences(chunk_text)),
                },
            )
            for idx, chunk_text in enumerate(chunks)
        ]
