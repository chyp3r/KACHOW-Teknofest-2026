from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import Document


class BaseChunker(ABC):
    """Metin chunker'ları/bölücüleri için soyut temel sınıf."""

    @abstractmethod
    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Girdi metnini bir Document nesneleri listesine böler.

        Args:
            text: Bölünecek ham metin dizesi.
            **kwargs: Uygulamaya özgü argümanlar.

        Returns:
            langchain_core.documents.Document nesnelerinden oluşan bir liste.
        """
        pass
