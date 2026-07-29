from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ai.embeddings.chunking.base import BaseChunker


class RecursiveChunker(BaseChunker):
    """Recursive Character Chunker that recursively splits text by looking at a list of characters

    (paragraphs, sentences, words, characters) to keep related text together.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Initialize Recursive Chunker.

        Args:
            chunk_size: Maximum size of each chunk.
            chunk_overlap: Number of overlapping characters between adjacent chunks.
        """
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Split text into chunks using RecursiveCharacterTextSplitter."""
        return self.splitter.create_documents([text])
