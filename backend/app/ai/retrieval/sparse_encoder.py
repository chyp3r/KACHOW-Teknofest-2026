import math
import zlib
import json
import os
import logging
from typing import List, Tuple, Dict
from langchain_core.documents import Document
from app.ai.retrieval.bm25 import tokenize_turkish

logger = logging.getLogger(__name__)


class SparseBM25Encoder:
    """Mathematical BM25 sparse vector encoder that uses CRC32 hashing for vocabulary mapping.

    Produces Qdrant-compatible sparse vectors offline without heavy external deep learning models.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.avg_doc_len = 0.0
        self.total_docs = 0
        self.idf: Dict[str, float] = {}

    def fit(self, documents: List[Document]):
        """Fit the BM25 parameters (IDF and average doc length) on the document corpus."""
        self.total_docs = len(documents)
        if self.total_docs == 0:
            return

        doc_lens = []
        doc_freqs: Dict[str, int] = {}

        for doc in documents:
            tokens = tokenize_turkish(doc.page_content)
            doc_lens.append(len(tokens))
            unique_tokens = set(tokens)
            for token in unique_tokens:
                doc_freqs[token] = doc_freqs.get(token, 0) + 1

        self.avg_doc_len = sum(doc_lens) / self.total_docs

        for token, freq in doc_freqs.items():
            # Standard BM25 IDF formula
            self.idf[token] = math.log(
                (self.total_docs - freq + 0.5) / (freq + 0.5) + 1.0
            )
        logger.info(
            f"Fitted SparseBM25Encoder: {self.total_docs} docs, average length {self.avg_doc_len:.2f}, vocabulary size {len(self.idf)}"
        )

    def encode_document(self, text: str) -> Tuple[List[int], List[float]]:
        """Encode document text into sparse indices and BM25 term weights."""
        tokens = tokenize_turkish(text)
        doc_len = len(tokens)
        if doc_len == 0:
            return [], []

        tf_dict: Dict[str, int] = {}
        for token in tokens:
            tf_dict[token] = tf_dict.get(token, 0) + 1

        indices = []
        values = []

        for token, tf in tf_dict.items():
            # BM25 TF scaling
            num = tf * (self.k1 + 1)
            denom = tf + self.k1 * (
                1.0 - self.b + self.b * (doc_len / (self.avg_doc_len or 1.0))
            )
            tf_scaled = num / denom

            # Index is the crc32 hash of the token
            idx = zlib.crc32(token.encode("utf-8"))
            indices.append(idx)
            values.append(float(tf_scaled))

        return indices, values

    def encode_query(self, query: str) -> Tuple[List[int], List[float]]:
        """Encode query text using IDF weights as values and hashed indices."""
        tokens = tokenize_turkish(query)
        if not tokens:
            return [], []

        indices = []
        values = []

        unique_tokens = set(tokens)
        for token in unique_tokens:
            idx = zlib.crc32(token.encode("utf-8"))
            # Query weight is its IDF value. Default to 1.0 for out-of-vocab tokens.
            val = self.idf.get(token, 1.0)
            indices.append(idx)
            values.append(float(val))

        return indices, values

    def save(self, filepath: str):
        """Save encoder parameters to a JSON file."""
        data = {
            "avg_doc_len": self.avg_doc_len,
            "total_docs": self.total_docs,
            "idf": self.idf,
        }
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved sparse vocabulary to {filepath}")

    def load(self, filepath: str) -> bool:
        """Load encoder parameters from a JSON file."""
        if not os.path.exists(filepath):
            logger.warning(f"Sparse vocabulary file not found at {filepath}")
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.avg_doc_len = data["avg_doc_len"]
            self.total_docs = data["total_docs"]
            self.idf = data["idf"]
            logger.info(
                f"Loaded sparse vocabulary from {filepath} (vocab size={len(self.idf)})"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load sparse vocabulary from {filepath}: {e}")
            return False
