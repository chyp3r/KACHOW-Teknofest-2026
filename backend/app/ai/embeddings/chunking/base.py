from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import Document


class BaseChunker(ABC):
    """Abstract base class for text chunkers/splitters."""

    @abstractmethod
    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Splits the input text into a list of Document objects.

        Args:
            text: The raw text string to split.
            **kwargs: Implementation-specific arguments.

        Returns:
            A list of langchain_core.documents.Document objects.
        """
        pass
