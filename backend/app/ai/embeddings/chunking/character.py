from typing import List

from langchain_core.documents import Document
from langchain_text_splitters import CharacterTextSplitter

from app.ai.embeddings.chunking.base import BaseChunker


class CharacterChunker(BaseChunker):
    """Character-based text splitter splitting by a single character (e.g. newline or space)

    and enforcing strict chunk sizes and overlaps.
    """

    def __init__(
        self,
        separator: str = "\n\n",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """Initialize Character Chunker.

        Args:
            separator: Character or string separator to split text on.
            chunk_size: Maximum size of each chunk.
            chunk_overlap: Number of overlapping characters between adjacent chunks.
        """
        self.splitter = CharacterTextSplitter(
            separator=separator,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Split text into chunks using CharacterTextSplitter."""
        # CharacterTextSplitter's create_documents returns a list of Documents
        return self.splitter.create_documents([text])
