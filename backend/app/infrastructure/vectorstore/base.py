from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.ai.embeddings.service import EmbeddedChunk


class BaseVectorStore(ABC):
    """Vektör veritabanı etkileşimleri için soyut temel sınıf."""

    @abstractmethod
    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        """Vektör veritabanında yeni bir koleksiyon oluştur.

        Args:
            collection_name: Koleksiyonun adı.
            vector_size: Vektörlerin boyutsallığı.
            distance: Mesafe metriği (örn. "Cosine", "Euclidean", "Dot").
        """
        pass

    @abstractmethod
    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        """Bir koleksiyondaki embed edilmiş parçaları ekle veya güncelle.

        Args:
            collection_name: Koleksiyonun adı.
            chunks: Metinler, vektörler ve metadata içeren EmbeddedChunk listesi.
        """
        pass

    @abstractmethod
    async def similarity_search(
        self, collection_name: str, query_vector: List[float], limit: int = 5, filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Bir koleksiyonda benzer vektörleri ara.

        Args:
            collection_name: Koleksiyonun adı.
            query_vector: Sorgu embedding vektörü.
            limit: Döndürülecek maksimum sonuç sayısı.

        Returns:
            Her biri bir eşleşmeyi (payload, skor, id) temsil eden bir sözlük nesneleri listesi.
        """
        pass

    @abstractmethod
    async def hybrid_search(
        self,
        collection_name: str,
        query_vector: List[float],
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Füzyon ile yoğun/seyrek (dense/sparse) hibrit vektör araması yap.

        Args:
            collection_name: Koleksiyonun adı.
            query_vector: Sorgu embedding vektörü.
            sparse_indices: Seyrek vektör jeton indeksleri.
            sparse_values: Seyrek vektör jeton değerleri (ağırlıklar).
            limit: Döndürülecek maksimum sonuç sayısı.

        Returns:
            Her biri bir eşleşmeyi temsil eden bir sözlük nesneleri listesi.
        """
        pass

    @abstractmethod
    async def delete_collection(self, collection_name: str) -> bool:
        """Vektör veritabanından bir koleksiyonu sil.

        Args:
            collection_name: Silinecek koleksiyonun adı.
        """
        pass

    @abstractmethod
    async def delete_by_filter(
        self, collection_name: str, filter_dict: Dict[str, Any]
    ) -> bool:
        """Koleksiyonu düşürmeden bir filtreyle eşleşen her noktayı sil.

        `delete_collection`'ın daha dar karşılığı -- diğer belgelerin hâlâ
        yaşadığı paylaşılan bir koleksiyondan tek bir belgenin parçalarını
        (örn. `{"storage_path": "uploads/x.pdf"}`) kaldırır.

        Args:
            collection_name: Koleksiyonun adı.
            filter_dict: Bu modülün filtre sözleşmesi (bkz.
                `QdrantStore._build_qdrant_filter`); boş olmamalıdır --
                boş bir filtre koleksiyonun tüm noktalarını silerdi.
        """
        pass

