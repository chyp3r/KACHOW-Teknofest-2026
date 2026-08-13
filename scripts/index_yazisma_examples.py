"""Index the curated few-shot draft example corpus into the vector store.

Run scripts/curate_yazisma_examples.py first to (re)generate ornekler.jsonl.

Usage (requires a running Qdrant and Ollama):
    python scripts/index_yazisma_examples.py
    python scripts/index_yazisma_examples.py --no-recreate
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.embeddings.models import get_embeddings_client
from app.core.config import settings
from app.infrastructure.vectorstore import get_vector_store
from app.workers.indexing import index_yazisma_examples


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yazışma örnek korpusunu indeksle.")
    parser.add_argument(
        "--examples-path",
        default=settings.RESMI_YAZISMA_EXAMPLES_PATH,
        help="ornekler.jsonl dosyasının yolu.",
    )
    parser.add_argument(
        "--collection",
        default=settings.RESMI_YAZISMA_COLLECTION_NAME,
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
    print("=" * 60)
    print("   Yazışma Örnek Korpusu İndeksleme")
    print("=" * 60)
    print(f"Örnek dosyası  : {args.examples_path}")
    print(f"Koleksiyon     : {args.collection}")
    print(f"Gömme modeli   : {settings.OLLAMA_EMBEDDING_MODEL}")
    print(f"Qdrant         : {settings.QDRANT_URL}\n")

    try:
        report = await index_yazisma_examples(
            examples_path=args.examples_path,
            collection_name=args.collection,
            embeddings_client=get_embeddings_client(),
            vector_store=get_vector_store(),
            recreate=not args.no_recreate,
        )
    except Exception as exc:
        print(f"\nHATA: {exc}")
        print("\nKontrol edin:")
        print(f"  1. Qdrant çalışıyor mu?  ({settings.QDRANT_URL})")
        print(f"  2. Ollama çalışıyor mu?  ({settings.OLLAMA_BASE_URL})")
        print(f"  3. '{settings.OLLAMA_EMBEDDING_MODEL}' modeli indirilmiş mi?")
        print(f"  4. '{args.examples_path}' dosyası mevcut mu? "
              "(önce scripts/curate_yazisma_examples.py çalıştırın)")
        return 1

    print("=" * 60)
    print(f"Tamamlandı: {report.chunk_count} örnek indekslendi.")
    print(f"Vektör boyutu: {report.vector_size}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
