"""Background indexing of the legislation corpus into the vector store.

The Qdrant collection is *derived state*: `datasets/mevzuat/` is the single source
of truth. Because `QdrantStore.upsert_documents` mints a random UUID per point,
re-running an index would duplicate every chunk and skew rank fusion, so the
worker rebuilds the collection from scratch instead of trying to reconcile.
"""

import logging

from pydantic import BaseModel, Field

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.embeddings.service import EmbeddedChunk
from app.ai.retrieval.corpus_loader import load_mevzuat_corpus
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

DIMENSION_PROBE_TEXT = "boyut testi"


class IndexingReport(BaseModel):
    """Outcome of an indexing run."""

    collection_name: str = Field(description="İndekslenen koleksiyonun adı.")
    chunk_count: int = Field(description="Yüklenen parça sayısı.")
    vector_size: int = Field(description="Tespit edilen gömme vektörü boyutu.")
    recreated: bool = Field(description="Koleksiyon sıfırdan oluşturuldu mu.")


async def index_mevzuat_corpus(
    *,
    corpus_dir: str,
    collection_name: str,
    embeddings_client: BaseEmbeddingsClient,
    vector_store: BaseVectorStore,
    chunker: BaseChunker,
    recreate: bool = True,
) -> IndexingReport:
    """Load, embed and upsert the legislation corpus.

    Args:
        corpus_dir: Directory holding the legislation markdown files.
        collection_name: Target vector-store collection.
        embeddings_client: Client used to embed chunks and probe the vector size.
        vector_store: Destination vector store.
        chunker: Chunking strategy; must match the one used by the BM25 path.
        recreate: Drop and recreate the collection before upserting.

    Returns:
        A report describing what was indexed.

    Raises:
        RuntimeError: If the corpus is empty or the vector store rejects the write.
    """
    documents = await load_mevzuat_corpus(corpus_dir, chunker)
    if not documents:
        raise RuntimeError(
            f"Mevzuat korpusu boş veya okunamadı: {corpus_dir}. İndeksleme yapılmadı."
        )

    # Probe the dimension rather than configuring it, so switching the embedding
    # model needs no code change and cannot silently disagree with a setting.
    probe = await embeddings_client.embed_query(DIMENSION_PROBE_TEXT)
    vector_size = len(probe)
    logger.info("Detected embedding dimension: %d", vector_size)

    if recreate:
        await vector_store.delete_collection(collection_name)

    created = await vector_store.create_collection(
        collection_name=collection_name, vector_size=vector_size
    )
    if not created:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonu oluşturulamadı; indeksleme durduruldu."
        )

    # Embed the loader's chunks directly instead of routing through
    # EmbeddingService.process_text: that helper re-chunks raw text, which would
    # produce different content than the BM25 path reads from the same corpus and
    # break the exact-content de-duplication rank fusion relies on.
    texts = [document.page_content for document in documents]
    vectors = await embeddings_client.embed_documents(texts)

    chunks = [
        EmbeddedChunk(
            text=document.page_content, vector=vector, metadata=document.metadata
        )
        for document, vector in zip(documents, vectors)
    ]

    # QdrantStore swallows exceptions and returns False. Without this check the
    # script would report success over an empty collection -- for example after an
    # embedding-model change leaves a stale collection with a different dimension.
    stored = await vector_store.upsert_documents(
        collection_name=collection_name, chunks=chunks
    )
    if not stored:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonuna yazma başarısız oldu. "
            "Koleksiyonun vektör boyutu gömme modeliyle uyuşmuyor olabilir."
        )

    logger.info(
        "Indexed %d chunk(s) into '%s' (vector_size=%d).",
        len(chunks),
        collection_name,
        vector_size,
    )
    return IndexingReport(
        collection_name=collection_name,
        chunk_count=len(chunks),
        vector_size=vector_size,
        recreated=recreate,
    )
