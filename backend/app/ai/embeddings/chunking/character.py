from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import CharacterTextSplitter

from app.ai.embeddings.chunking.base import BaseChunker


class CharacterChunker(BaseChunker):
    """Tek bir karaktere göre (ör. yeni satır veya boşluk) bölen ve sıkı parça

    boyutları ile örtüşmeleri zorunlu kılan karakter tabanlı metin bölücü.
    """

    def __init__(
        self,
        separator: str = "\n\n",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """Character Chunker'ı başlatır.

        Args:
            separator: Metnin bölüneceği karakter veya dize ayırıcı.
            chunk_size: Her parçanın maksimum boyutu.
            chunk_overlap: Komşu parçalar arasındaki örtüşen karakter sayısı.
        """
        self.splitter = CharacterTextSplitter(
            separator=separator,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Metni CharacterTextSplitter kullanarak parçalara böler."""
        # CharacterTextSplitter'ın create_documents metodu bir Document listesi döndürür
        return self.splitter.create_documents([text])
