import logging
import re
from typing import List, Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


def tokenize_turkish(text: str) -> List[str]:
    """Türkçe için optimize edilmiş basit tokenizer.

    Metni Türkçe harf farkındalığıyla küçük harfe çevirir ve token'ları çıkarır.
    """
    if not text:
        return []

    # Büyük Türkçe harfleri küçük harfe eşle
    turkish_map = {
        "I": "ı",
        "İ": "i",
        "Ç": "ç",
        "Ş": "ş",
        "Ğ": "ğ",
        "Ü": "ü",
        "Ö": "ö",
    }
    text_mapped = "".join(turkish_map.get(char, char.lower()) for char in text)

    # Regex ile kelime/token çıkar (alfanümerik diziler)
    tokens = re.findall(r"\w+", text_mapped)

    # Kısa, stop-word benzeri token'ları filtrele
    return [t for t in tokens if len(t) > 1]


class BM25Retriever:
    """BM25Okapi algoritmasını kullanan seyrek (sparse) anahtar kelime arama retriever'ı."""

    def __init__(self):
        """BM25 Retriever'ı başlat."""
        self.documents: List[Document] = []
        self.bm25: Optional[BM25Okapi] = None
        logger.info("Initialized BM25Retriever.")

    def index_documents(self, documents: List[Document]) -> None:
        """Document nesneleri kümesini tokenize et ve bir BM25 indeksi oluştur.

        Args:
            documents: Metin korpusunu içeren Document nesneleri listesi.
        """
        if not documents:
            logger.warning("BM25Retriever: Attempted to index empty list of documents.")
            self.documents = []
            self.bm25 = None
            return

        self.documents = documents
        # Her belgeyi tokenize et
        tokenized_corpus = [
            tokenize_turkish(doc.page_content) for doc in documents
        ]
        self.bm25 = BM25Okapi(tokenized_corpus)
        logger.info(f"BM25Retriever successfully indexed {len(documents)} documents.")

    async def retrieve(self, query: str, limit: int = 5) -> List[Document]:
        """İndekslenmiş korpus üzerinde seyrek anahtar kelime araması yap.

        Args:
            query: Kullanıcının arama sorgusu.
            limit: Döndürülecek maksimum belge sayısı.
        """
        if not self.bm25 or not self.documents or not query.strip():
            return []

        try:
            # Sorguyu tokenize et
            tokenized_query = tokenize_turkish(query)
            if not tokenized_query:
                return []

            # Korpustaki tüm belgeler için skorları al
            scores = self.bm25.get_scores(tokenized_query)

            # Belgeleri skora göre sırala
            doc_scores = list(zip(self.documents, scores))
            # Sıfır veya negatif skorlu belgeleri filtrele
            valid_doc_scores = [(doc, float(score)) for doc, score in doc_scores if score > 0.0]
            sorted_docs = sorted(valid_doc_scores, key=lambda x: x[1], reverse=True)

            # En üstteki limit kadarını al
            hits = sorted_docs[:limit]

            # Belgeleri skor metadata'sıyla biçimlendir
            formatted_docs = []
            for doc, score in hits:
                # Orijinali değiştirmemek için belgeyi kopyala
                new_doc = Document(
                    page_content=doc.page_content, metadata=doc.metadata.copy()
                )
                new_doc.metadata["score"] = score
                formatted_docs.append(new_doc)

            logger.info(
                f"BM25Retriever found {len(formatted_docs)} matches for query: '{query[:30]}...'"
            )
            return formatted_docs

        except Exception as e:
            logger.error(
                f"BM25Retriever search failed for query '{query}': {e}",
                exc_info=True,
            )
            return []
