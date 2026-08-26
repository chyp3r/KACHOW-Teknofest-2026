from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ai.embeddings.chunking.base import BaseChunker


class RecursiveChunker(BaseChunker):
    """İlgili metinleri bir arada tutmak için bir karakter listesine

    (paragraflar, cümleler, kelimeler, karakterler) bakarak metni özyinelemeli
    olarak bölen Recursive Character Chunker.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Recursive Chunker'ı başlatır.

        Args:
            chunk_size: Her parçanın maksimum boyutu.
            chunk_overlap: Komşu parçalar arasındaki örtüşen karakter sayısı.
        """
        # add_start_index her parçanın metadata'sını kaynak metindeki karakter
        # ofsetiyle etiketler; bu da bir parçanın PageMap üzerinden bir sayfa
        # numarasına eşlenmesini sağlar (bkz. app.ai.documents.anchors).
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, add_start_index=True
        )

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Metni RecursiveCharacterTextSplitter kullanarak parçalara böler."""
        return self.splitter.create_documents([text])
