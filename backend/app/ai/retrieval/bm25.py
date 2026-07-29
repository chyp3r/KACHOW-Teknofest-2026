import logging
import re
from typing import List, Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


def tokenize_turkish(text: str) -> List[str]:
    """SOTA basic tokenizer optimized for Turkish language.

    Converts text to lowercase with Turkish letter awareness and extracts tokens.
    """
    if not text:
        return []

    # Map uppercase Turkish letters to lowercase
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

    # Extract words/tokens using regex (alphanumeric sequences)
    tokens = re.findall(r"\w+", text_mapped)

    # Filter out short stop-word-like tokens
    return [t for t in tokens if len(t) > 1]


class BM25Retriever:
    """Sparse keyword search retriever utilizing the BM25Okapi algorithm."""

    def __init__(self):
        """Initialize BM25 Retriever."""
        self.documents: List[Document] = []
        self.bm25: Optional[BM25Okapi] = None
        logger.info("Initialized BM25Retriever.")

    def index_documents(self, documents: List[Document]) -> None:
        """Tokenize and build a BM25 index on a set of Document objects.

        Args:
            documents: List of Document objects containing the text corpus.
        """
        if not documents:
            logger.warning("BM25Retriever: Attempted to index empty list of documents.")
            self.documents = []
            self.bm25 = None
            return

        self.documents = documents
        # Tokenize each document
        tokenized_corpus = [
            tokenize_turkish(doc.page_content) for doc in documents
        ]
        self.bm25 = BM25Okapi(tokenized_corpus)
        logger.info(f"BM25Retriever successfully indexed {len(documents)} documents.")

    async def retrieve(self, query: str, limit: int = 5) -> List[Document]:
        """Perform sparse keyword search against the indexed corpus.

        Args:
            query: User search query.
            limit: Maximum documents to return.
        """
        if not self.bm25 or not self.documents or not query.strip():
            return []

        try:
            # Tokenize query
            tokenized_query = tokenize_turkish(query)
            if not tokenized_query:
                return []

            # Get scores for all documents in the corpus
            scores = self.bm25.get_scores(tokenized_query)

            # Sort documents by score
            doc_scores = list(zip(self.documents, scores))
            # Filter out documents with zero or negative score
            valid_doc_scores = [(doc, float(score)) for doc, score in doc_scores if score > 0.0]
            sorted_docs = sorted(valid_doc_scores, key=lambda x: x[1], reverse=True)

            # Take top limit
            hits = sorted_docs[:limit]

            # Format documents with score metadata
            formatted_docs = []
            for doc, score in hits:
                # Copy document to avoid mutating original
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
