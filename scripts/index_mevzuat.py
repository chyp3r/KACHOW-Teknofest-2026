"""Index the legislation corpus into the vector store.

Usage (requires a running Qdrant and Ollama):
    python scripts/index_mevzuat.py
    python scripts/index_mevzuat.py --no-recreate
"""

import argparse
import asyncio
import os
import sys

# Add backend directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.embeddings.models import get_embeddings_client
from app.ai.policy import get_policy
from app.core.config import settings
from app.infrastructure.vectorstore import get_vector_store
from app.workers.indexing import index_mevzuat_corpus

# Sourced from ChunkingPolicy.mevzuat_* -- must match the parameters used
# by the BM25 dependency (app.ai.retrieval.mcp_mevzuat), otherwise rank
# fusion sees the same passage twice.
CHUNK_SIZE = get_policy().chunking.mevzuat_chunk_size
CHUNK_OVERLAP = get_policy().chunking.mevzuat_chunk_overlap


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mevzuat korpusunu indeksle.")
    parser.add_argument(
        "--corpus-dir",
        default=settings.MEVZUAT_CORPUS_DIR,
        help="Mevzuat metinlerinin bulunduğu klasör.",
    )
    parser.add_argument(
        "--collection",
        default=settings.MEVZUAT_COLLECTION_NAME,
        help="Hedef koleksiyon adı.",
    )
    parser.add_argument(
        "--no-recreate",
        action="store_true",
        help="Koleksiyonu silip yeniden oluşturmadan üzerine yaz.",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    # Built once, up front, so the banner below reports what get_embeddings_
    # client()/get_vector_store() actually resolved to (LOCAL_MODE-dependent
    # -- Ollama or Evren) instead of hardcoding the Ollama/local settings,
    # which used to print "nomic-embed-text"/local Qdrant even while the
    # real call underneath was already going to Evren's bge-m3-embed --
    # confusingly wrong, not just cosmetic, since a reader has no other way
    # to tell which provider a given run actually used.
    embeddings_client = get_embeddings_client()
    vector_store = get_vector_store()
    print("=" * 60)
    print("   Mevzuat Korpusu İndeksleme")
    print("=" * 60)
    print(f"Korpus klasörü : {args.corpus_dir}")
    print(f"Koleksiyon     : {args.collection}")
    print(f"Gömme modeli   : {embeddings_client.model_name} ({embeddings_client.base_url})")
    print(f"Qdrant         : {vector_store.qdrant_url}\n")

    try:
        report = await index_mevzuat_corpus(
            corpus_dir=args.corpus_dir,
            collection_name=args.collection,
            embeddings_client=embeddings_client,
            vector_store=vector_store,
            chunker=RecursiveChunker(
                chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
            ),
            recreate=not args.no_recreate,
        )
    except Exception as exc:
        print(f"\nHATA: {exc}")
        print("\nKontrol edin:")
        print(f"  1. Qdrant çalışıyor mu?  ({vector_store.qdrant_url})")
        print(f"  2. Gömme servisi çalışıyor mu?  ({embeddings_client.base_url})")
        print(f"  3. '{embeddings_client.model_name}' modeli erişilebilir mi?")
        print(f"  4. '{args.corpus_dir}' klasöründe .md dosyaları var mı?")
        return 1

    print("=" * 60)
    print(f"Tamamlandı: {report.chunk_count} parça indekslendi.")
    print(f"Vektör boyutu: {report.vector_size}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
