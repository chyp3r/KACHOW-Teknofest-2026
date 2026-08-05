import logging
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.ai.embeddings.service import EmbeddedChunk
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

#: Name of the sparse vector used by the hybrid retriever. Collections created
#: before this was introduced do not have it, and Qdrant rejects any query that
#: names a vector the collection lacks.
SPARSE_VECTOR_NAME = "text-sparse"

#: Range-condition operator keys a ``filter_dict`` value may use instead of a
#: plain scalar (exact match) -- e.g. ``{"sensitivity_rank": {"lte": 3}}``
#: restricts a search to chunks whose payload field is at or below 3. Named
#: after Qdrant's own ``models.Range`` fields, passed straight through.
_RANGE_OPERATORS = frozenset({"lt", "lte", "gt", "gte"})


def _build_qdrant_filter(filter_dict: Optional[Dict[str, Any]]) -> Optional[models.Filter]:
    """Translate this module's ``filter_dict`` convention into a Qdrant filter.

    A value is either a scalar (exact match, the original and still most
    common case -- ``{"storage_path": "uploads/x.pdf"}``) or a dict of range
    operators (``{"sensitivity_rank": {"lte": 3}}``), used to restrict a
    search by an ordered numeric payload field -- e.g. RBAC clearance
    filtering, where a chunk above the requester's rank must never be
    returned from the vector search at all, not merely filtered out
    downstream after the model has already seen it.

    Args:
        filter_dict: This module's filter convention, or None/empty for no
            filter.

    Returns:
        The equivalent Qdrant filter, or None when ``filter_dict`` is empty.
    """
    if not filter_dict:
        return None

    must_conditions = []
    for key, val in filter_dict.items():
        if isinstance(val, dict):
            range_kwargs = {op: bound for op, bound in val.items() if op in _RANGE_OPERATORS}
            must_conditions.append(
                models.FieldCondition(key=key, range=models.Range(**range_kwargs))
            )
        else:
            must_conditions.append(
                models.FieldCondition(key=key, match=models.MatchValue(value=val))
            )
    return models.Filter(must=must_conditions)


class QdrantStore(BaseVectorStore):
    """Qdrant client implementation of BaseVectorStore for vector storage and search."""

    def __init__(self, qdrant_url: str):
        """Initialize Qdrant Store client.

        Args:
            qdrant_url: Endpoint URL of Qdrant DB (e.g. "http://localhost:6333").
        """
        self.qdrant_url = qdrant_url
        self.client = AsyncQdrantClient(url=qdrant_url)
        # Cache of collection_name -> "does it have a sparse vector". Probed once
        # per process so a stale collection costs one extra call, not one failed
        # query (and one stack trace) per retrieval.
        self._sparse_support: Dict[str, bool] = {}
        logger.info(f"Initialized AsyncQdrantClient targeting: {qdrant_url}")

    async def _has_sparse_vector(self, collection_name: str) -> bool:
        """Report whether a collection is configured for sparse vectors.

        Args:
            collection_name: The collection to inspect.

        Returns:
            True when the collection declares the sparse vector the hybrid
            retriever needs. Unknown or unreachable collections report False, so
            retrieval degrades to dense-only rather than erroring.
        """
        cached = self._sparse_support.get(collection_name)
        if cached is not None:
            return cached

        try:
            info = await self.client.get_collection(collection_name)
            sparse_config = getattr(info.config.params, "sparse_vectors", None) or {}
            has_sparse = SPARSE_VECTOR_NAME in sparse_config
        except Exception:
            logger.warning(
                "Could not inspect collection '%s'; assuming no sparse vectors.",
                collection_name,
            )
            has_sparse = False

        if not has_sparse:
            logger.warning(
                "Collection '%s' has no '%s' vector, so hybrid search will run "
                "dense-only. The collection predates hybrid indexing; re-run "
                "scripts/index_mevzuat.py to rebuild it with sparse vectors.",
                collection_name,
                SPARSE_VECTOR_NAME,
            )

        self._sparse_support[collection_name] = has_sparse
        return has_sparse

    async def create_collection(
        self, collection_name: str, vector_size: int, distance: str = "Cosine"
    ) -> bool:
        """Create the collection, or validate the schema of an existing one.

        An existing collection is *checked*, not blindly accepted. The previous
        version returned success on any existing collection, so one created
        before sparse vectors existed stayed permanently incompatible with
        hybrid search while every retrieval logged a 400 from Qdrant.

        Args:
            collection_name: Target collection.
            vector_size: Dense vector dimensionality.
            distance: Distance metric name.

        Returns:
            True when the collection exists and is usable for dense search.
        """
        dist_enum = models.Distance.COSINE
        dist_lower = distance.lower()
        if dist_lower == "euclidean":
            dist_enum = models.Distance.EUCLID
        elif dist_lower == "dot":
            dist_enum = models.Distance.DOT

        try:
            if await self.client.collection_exists(collection_name):
                return await self._validate_existing(collection_name, vector_size)

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=dist_enum
                ),
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: models.SparseVectorParams(
                        index=models.SparseIndexParams(on_disk=True)
                    )
                },
            )
            self._sparse_support[collection_name] = True
            logger.info(
                "Created Qdrant collection '%s' (dense=%d, sparse=%s).",
                collection_name,
                vector_size,
                SPARSE_VECTOR_NAME,
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant create_collection failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def _validate_existing(
        self, collection_name: str, vector_size: int
    ) -> bool:
        """Check that an existing collection matches what the code expects.

        Args:
            collection_name: The collection to check.
            vector_size: The dense dimensionality the caller intends to write.

        Returns:
            True when the collection can accept dense writes of this size.
        """
        try:
            info = await self.client.get_collection(collection_name)
            params = info.config.params

            existing_vectors = params.vectors
            existing_size = getattr(existing_vectors, "size", None)
            if existing_size is None and isinstance(existing_vectors, dict):
                default = existing_vectors.get("")
                existing_size = getattr(default, "size", None)

            if existing_size is not None and existing_size != vector_size:
                # Writing 768-dim vectors into a 3584-dim collection fails on
                # every point and is otherwise only visible as a silent no-op.
                logger.error(
                    "Collection '%s' has dimension %d but the embedding model "
                    "produces %d. Delete the collection and re-index.",
                    collection_name,
                    existing_size,
                    vector_size,
                )
                return False

            sparse_config = getattr(params, "sparse_vectors", None) or {}
            has_sparse = SPARSE_VECTOR_NAME in sparse_config
            self._sparse_support[collection_name] = has_sparse
            if not has_sparse:
                logger.warning(
                    "Collection '%s' exists without a '%s' vector; hybrid search "
                    "will fall back to dense-only. Re-index to enable it.",
                    collection_name,
                    SPARSE_VECTOR_NAME,
                )
            else:
                logger.info("Collection '%s' already exists and is valid.", collection_name)
            return True
        except Exception as e:
            logger.error(
                f"Could not validate existing collection '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def upsert_documents(
        self, collection_name: str, chunks: List[EmbeddedChunk]
    ) -> bool:
        """Upsert embedded chunks into Qdrant collection."""
        if not chunks:
            return True

        points = []
        for chunk in chunks:
            point_id = str(uuid.uuid4())
            # Save raw text inside payload along with any metadata keys
            payload = {"text": chunk.text, **chunk.metadata}
            
            # Format vector based on presence of sparse vector
            if chunk.sparse_vector:
                vector_data = {
                    "": chunk.vector,
                    "text-sparse": models.SparseVector(
                        indices=chunk.sparse_vector["indices"],
                        values=chunk.sparse_vector["values"],
                    ),
                }
            else:
                vector_data = chunk.vector

            points.append(
                models.PointStruct(
                    id=point_id, vector=vector_data, payload=payload
                )
            )

        try:
            await self.client.upsert(
                collection_name=collection_name, points=points
            )
            logger.debug(
                f"Upserted {len(chunks)} chunks to collection '{collection_name}'."
            )
            return True
        except Exception as e:
            logger.error(
                f"Qdrant upsert failed for collection '{collection_name}': {e}",
                exc_info=True,
            )
            return False

    async def similarity_search(
        self, collection_name: str, query_vector: List[float], limit: int = 5, filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search similar vectors in Qdrant collection and return normalized payload objects."""
        try:
            # `search()` was removed in qdrant-client 1.x in favour of
            # `query_points()`. Because this method swallows exceptions and returns
            # an empty list, calling the removed API made every dense lookup return
            # no hits silently, degrading hybrid retrieval to sparse-only.
            qdrant_filter = _build_qdrant_filter(filter_dict)

            response = await self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
            )

            hits = []
            for hit in response.points:
                payload = hit.payload or {}
                # Pop out the raw text key
                text = payload.pop("text", "")
                hits.append(
                    {"text": text, "score": hit.score, "metadata": payload}
                )
            return hits
        except Exception as e:
            logger.error(
                f"Qdrant similarity_search failed in '{collection_name}': {e}",
                exc_info=True,
            )
            return []

    async def hybrid_search(
        self,
        collection_name: str,
        query_vector: List[float],
        sparse_indices: List[int],
        sparse_values: List[float],
        limit: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform native hybrid search using Qdrant Prefetch API and RRF fusion."""
        try:
            qdrant_filter = _build_qdrant_filter(filter_dict)

            # Define prefetch queries for dense and sparse
            dense_prefetch = models.Prefetch(
                query=query_vector,
                using="",  # Default dense vector
                limit=limit * 3,  # Fetch more candidates to fuse
                filter=qdrant_filter,
            )

            prefetch_list = [dense_prefetch]
            # Only prefetch sparse when the query has tokens *and* the collection
            # actually declares the vector. Naming a vector the collection lacks
            # makes Qdrant reject the whole request with a 400.
            if (
                sparse_indices
                and sparse_values
                and await self._has_sparse_vector(collection_name)
            ):
                prefetch_list.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_indices,
                            values=sparse_values,
                        ),
                        using=SPARSE_VECTOR_NAME,
                        limit=limit * 3,
                        filter=qdrant_filter,
                    )
                )

            # A single prefetch branch has nothing to fuse; go straight to dense
            # search rather than paying for a degenerate RRF round trip.
            if len(prefetch_list) == 1:
                return await self.similarity_search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    limit=limit,
                    filter_dict=filter_dict,
                )

            # Query Qdrant with Fusion (Reciprocal Rank Fusion)
            response = await self.client.query_points(
                collection_name=collection_name,
                prefetch=prefetch_list,
                query=models.FusionQuery(
                    fusion=models.Fusion.RRF
                ),
                limit=limit,
            )

            hits = []
            for hit in response.points:
                payload = hit.payload or {}
                text = payload.pop("text", "")
                hits.append(
                    {"text": text, "score": hit.score, "metadata": payload}
                )
            return hits
        except Exception as e:
            # Logged without a traceback: the dense fallback below still answers
            # the query, so this is a degradation notice, not a crash. Emitting a
            # full stack trace per retrieval buried the real errors in the log.
            logger.warning(
                "Qdrant hybrid_search failed in '%s' (%s); falling back to dense search.",
                collection_name,
                e,
            )
            self._sparse_support[collection_name] = False
            # Fallback to similarity search
            return await self.similarity_search(
                collection_name=collection_name,
                query_vector=query_vector,
                limit=limit,
                filter_dict=filter_dict,
            )

    async def delete_collection(self, collection_name: str) -> bool:
        """Delete a collection from Qdrant database."""
        try:
            exists = await self.client.collection_exists(collection_name)
            if not exists:
                logger.info(
                    f"Collection '{collection_name}' does not exist, no need to delete."
                )
                return True
            await self.client.delete_collection(collection_name)
            logger.info(f"Deleted Qdrant collection: '{collection_name}'")
            return True
        except Exception as e:
            logger.error(
                f"Qdrant delete_collection failed for '{collection_name}': {e}",
                exc_info=True,
            )
            return False

