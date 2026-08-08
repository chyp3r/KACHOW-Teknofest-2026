"""Background indexing of source corpora into the vector store.

Both indexers below treat their Qdrant collection as *derived state*: a
committed dataset directory is the single source of truth. Because
`QdrantStore.upsert_documents` mints a random UUID per point, re-running an
index would duplicate every point and skew rank fusion, so each worker
rebuilds its collection from scratch instead of trying to reconcile.
"""

import logging
import os

from pydantic import BaseModel, Field

from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.embeddings.service import EmbeddedChunk
from app.ai.retrieval.corpus_loader import load_mevzuat_corpus, load_yazisma_examples
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

DIMENSION_PROBE_TEXT = "boyut testi"

#: Correspondence-type labels used only to build the embedded descriptor
#: below -- kept local (rather than importing the workflow's Turkish-label
#: table) so this module has no dependency on the draft workflow package.
_TYPE_LABELS = {
    "cover_letter": "Üst yazı",
    "response_letter": "Cevap yazısı",
    "information_notice": "Bilgilendirme metni",
    "other_official": "Diğer resmî yazışma",
}

#: How much of the full letter body feeds the embedded descriptor. The point
#: payload always stores the full text (see below); only the *search key* is
#: truncated, because a query is a short topic sentence and embedding the
#: full body would bury that signal under boilerplate header/signature text.
DESCRIPTOR_BODY_CHARS = 600


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

    import os
    from app.ai.retrieval.sparse_encoder import SparseBM25Encoder

    # Fit and save sparse encoder for hybrid search
    encoder = SparseBM25Encoder()
    encoder.fit(documents)
    vocab_path = os.path.join(corpus_dir, "sparse_vocab.json")
    encoder.save(vocab_path)

    texts = [document.page_content for document in documents]
    vectors = await embeddings_client.embed_documents(texts)

    chunks = []
    for document, vector in zip(documents, vectors):
        indices, values = encoder.encode_document(document.page_content)
        chunks.append(
            EmbeddedChunk(
                text=document.page_content,
                vector=vector,
                metadata=document.metadata,
                sparse_vector={"indices": indices, "values": values},
            )
        )

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


def _build_descriptor(record: dict) -> str:
    """Build the short text a style example is embedded and sparse-encoded on.

    Deliberately not the full letter body: a retrieval query is a short topic
    sentence (subject + user instructions), and embedding an entire letter
    would let its boilerplate header/signature block dilute the one sentence
    that actually distinguishes it from the other examples of the same type.
    """
    type_label = _TYPE_LABELS.get(record["correspondence_type"], record["correspondence_type"])
    return (
        f"{record.get('baslik', '')}\n"
        f"{type_label} / {record.get('niyet', '')}\n"
        f"{record.get('text', '')[:DESCRIPTOR_BODY_CHARS]}"
    )


async def index_yazisma_examples(
    *,
    examples_path: str,
    collection_name: str,
    embeddings_client: BaseEmbeddingsClient,
    vector_store: BaseVectorStore,
    recreate: bool = True,
) -> IndexingReport:
    """Embed and upsert the curated few-shot draft example corpus.

    Unlike ``index_mevzuat_corpus`` there is no chunking step: each JSONL
    record produced by ``scripts/curate_yazisma_examples.py`` is already a
    single full official letter, and a few-shot example has to stay whole to
    teach a complete document structure. Only a short descriptor (see
    ``_build_descriptor``) is embedded and sparse-encoded; the point payload
    carries the full letter text, which is what the draft writer prompt
    actually needs back.

    Args:
        examples_path: Path to ``ornekler.jsonl``.
        collection_name: Target vector-store collection.
        embeddings_client: Client used to embed descriptors and probe the
            vector size.
        vector_store: Destination vector store.
        recreate: Drop and recreate the collection before upserting.

    Returns:
        A report describing what was indexed.

    Raises:
        RuntimeError: If the corpus is empty or the vector store rejects the
            write.
    """
    from langchain_core.documents import Document

    records = load_yazisma_examples(examples_path)
    if not records:
        raise RuntimeError(
            f"Yazışma örnek korpusu boş veya okunamadı: {examples_path}. İndeksleme yapılmadı."
        )

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

    from app.ai.retrieval.sparse_encoder import SparseBM25Encoder

    descriptors = [_build_descriptor(record) for record in records]

    encoder = SparseBM25Encoder()
    encoder.fit([Document(page_content=descriptor) for descriptor in descriptors])
    vocab_path = os.path.join(os.path.dirname(examples_path), "sparse_vocab.json")
    encoder.save(vocab_path)

    vectors = await embeddings_client.embed_documents(descriptors)

    chunks = []
    for record, descriptor, vector in zip(records, descriptors, vectors):
        indices, values = encoder.encode_document(descriptor)
        chunks.append(
            EmbeddedChunk(
                text=record["text"],
                vector=vector,
                metadata={
                    "example_id": record["id"],
                    "correspondence_type": record["correspondence_type"],
                    "kategori": record.get("kategori", ""),
                    "niyet": record.get("niyet", ""),
                    "baslik": record.get("baslik", ""),
                    "kurum": record.get("kurum", ""),
                    "char_len": record.get("char_len", len(record["text"])),
                    "source_path": record.get("source_path", ""),
                },
                sparse_vector={"indices": indices, "values": values},
            )
        )

    # Same rationale as index_mevzuat_corpus: QdrantStore swallows exceptions
    # and returns False, so this check is what turns a dimension mismatch
    # into a loud failure instead of a silently empty collection.
    stored = await vector_store.upsert_documents(
        collection_name=collection_name, chunks=chunks
    )
    if not stored:
        raise RuntimeError(
            f"'{collection_name}' koleksiyonuna yazma başarısız oldu. "
            "Koleksiyonun vektör boyutu gömme modeliyle uyuşmuyor olabilir."
        )

    logger.info(
        "Indexed %d yazışma örneği into '%s' (vector_size=%d).",
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
