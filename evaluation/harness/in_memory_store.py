"""A BaseVectorStore-shaped stand-in for Qdrant, used only by the retrieval
evaluation suite.

``make eval`` runs with ``--no-deps`` and touches no infrastructure -- that
invariant is the whole point of the harness (see the ``Makefile``'s comment
on the ``eval`` target). A Qdrant-dependent retrieval suite would be the
first suite that cannot run offline, so this exists to keep it out.

The dense ranking is plain cosine similarity over cached vectors; the
sparse ranking reuses the real ``app.ai.retrieval.sparse_encoder.
SparseBM25Encoder``; fusion reuses the real
``app.ai.retrieval.fusion.reciprocal_rank_fusion``. Injected as the
``vector_store`` of a real ``app.ai.retrieval.hybrid.HybridRetriever``, the
exercised path is production retrieval code end to end -- embed query,
sparse-encode query, hybrid search, ``Document`` mapping with
``metadata["score"]`` -- and only the storage layer is stubbed.

Honest limitation worth stating up front: production Qdrant fuses natively
via ``models.Fusion.RRF`` (Rust); this uses the Python
``reciprocal_rank_fusion``. Both implement the same formula, but tie-
breaking and float ordering can differ marginally on score ties. This
suite measures the retrieval *shape* (chunking, corpus content, query
formulation) -- it is not a substitute for measuring the serving stack
itself.
"""

import math
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from app.ai.embeddings.service import EmbeddedChunk
from app.ai.retrieval.fusion import reciprocal_rank_fusion
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.infrastructure.vectorstore.base import BaseVectorStore


def _cosine_similarity(u: List[float], v: List[float]) -> float:
    """Plain cosine similarity; degenerate (zero-norm) vectors score 0.0
    rather than raising, since a chunk that embedded to an all-zero vector
    is a data problem, not a reason to crash a batch eval run."""
    dot = sum(a * b for a, b in zip(u, v))
    norm_u = math.sqrt(sum(a * a for a in u))
    norm_v = math.sqrt(sum(b * b for b in v))
    if norm_u == 0.0 or norm_v == 0.0:
        return 0.0
    return dot / (norm_u * norm_v)


def _sparse_dot(
    doc_indices: List[int],
    doc_values: List[float],
    query_indices: List[int],
    query_values: List[float],
) -> float:
    """Dot product over the shared indices of two sparse vectors."""
    doc_weights = dict(zip(doc_indices, doc_values))
    query_weights = dict(zip(query_indices, query_values))
    shared = doc_weights.keys() & query_weights.keys()
    return sum(doc_weights[idx] * query_weights[idx] for idx in shared)


def _matches_filter(metadata: Dict[str, Any], filter_dict: Optional[Dict[str, Any]]) -> bool:
    """Same convention ``QdrantStore._build_qdrant_filter`` implements for
    the shapes this codebase actually sends it: every key must be present
    in the point's metadata with an equal value."""
    if not filter_dict:
        return True
    return all(metadata.get(key) == value for key, value in filter_dict.items())


class InMemoryHybridStore(BaseVectorStore):
    """Holds embedded chunks in a plain dict; answers ``hybrid_search`` by
    ranking dense and sparse independently, then RRF-fusing, exactly the
    two-list-in shape ``reciprocal_rank_fusion`` expects.

    Every other ``BaseVectorStore`` method is implemented too (so this is a
    complete, real vector store for anything that only needs an in-process
    one), but the retrieval suite only ever calls ``load`` and, through
    ``HybridRetriever``, ``hybrid_search``.
    """

    def __init__(self) -> None:
        self._collections: Dict[str, List[Dict[str, Any]]] = {}

    def load(self, collection_name: str, chunks: List[EmbeddedChunk]) -> None:
        """Populate a collection directly from embedded chunks, bypassing
        ``upsert_documents``'s ``bool`` return -- the eval never needs to
        check it, and a direct list assignment makes a fixture's intent
        (call this once per arm, before searching) obvious at the call
        site."""
        self._collections[collection_name] = [
            {
                "text": chunk.text,
                "vector": chunk.vector,
                "metadata": dict(chunk.metadata),
                "sparse_vector": chunk.sparse_vector or {"indices": [], "values": []},
            }
            for chunk in chunks
        ]

    async def hybrid_search(
        self,
        collection_name: str,
        query_vector: List[float],
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        points = [
            point
            for point in self._collections.get(collection_name, [])
            if _matches_filter(point["metadata"], filter_dict)
        ]
        if not points:
            return []

        dense_ranked = sorted(
            points,
            key=lambda point: _cosine_similarity(point["vector"], query_vector),
            reverse=True,
        )
        sparse_ranked = sorted(
            points,
            key=lambda point: _sparse_dot(
                point["sparse_vector"]["indices"],
                point["sparse_vector"]["values"],
                sparse_indices,
                sparse_values,
            ),
            reverse=True,
        )

        def _to_documents(ranked: List[Dict[str, Any]]) -> List[Document]:
            return [
                Document(page_content=point["text"], metadata=point["metadata"])
                for point in ranked
            ]

        fused = reciprocal_rank_fusion([_to_documents(dense_ranked), _to_documents(sparse_ranked)])

        return [
            {
                "text": doc.page_content,
                "metadata": {k: v for k, v in doc.metadata.items() if k != "rrf_score"},
                "score": doc.metadata.get("rrf_score", 0.0),
            }
            for doc in fused[:limit]
        ]

    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        self._collections.setdefault(collection_name, [])
        return True

    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        self._collections.setdefault(collection_name, [])
        self._collections[collection_name].extend(
            {
                "text": chunk.text,
                "vector": chunk.vector,
                "metadata": dict(chunk.metadata),
                "sparse_vector": chunk.sparse_vector or {"indices": [], "values": []},
            }
            for chunk in chunks
        )
        return True

    async def similarity_search(
        self,
        collection_name: str,
        query_vector: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        points = [
            point
            for point in self._collections.get(collection_name, [])
            if _matches_filter(point["metadata"], filter_dict)
        ]
        ranked = sorted(
            points,
            key=lambda point: _cosine_similarity(point["vector"], query_vector),
            reverse=True,
        )
        return [
            {"text": point["text"], "metadata": point["metadata"], "score": _cosine_similarity(point["vector"], query_vector)}
            for point in ranked[:limit]
        ]

    async def delete_collection(self, collection_name: str) -> bool:
        self._collections.pop(collection_name, None)
        return True

    async def delete_by_filter(self, collection_name: str, filter_dict: Dict[str, Any]) -> bool:
        if not filter_dict:
            return False
        points = self._collections.get(collection_name)
        if points is None:
            return True
        self._collections[collection_name] = [
            point for point in points if not _matches_filter(point["metadata"], filter_dict)
        ]
        return True
