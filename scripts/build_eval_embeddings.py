"""Precomputes embeddings for every message in the intent gold set.

Run once after editing ``evaluation/datasets/intents.jsonl``:

    docker compose run --rm --no-deps backend python scripts/build_eval_embeddings.py

Mirrors ``scripts/build_prototypes.py``'s reasoning exactly: ``make eval``
embeds nothing at request time, so measuring the semantic rung
(``app.ai.semantic.prototype_matcher``) against the real gold set needs its
messages embedded once, offline, and cached -- see
``evaluation.harness.cached_embeddings.CachedEmbeddingsClient``, which reads
this file's output and never calls a model.

Every message is embedded (not deduplicated first): a stable, indexable file
keyed by exact text is worth a handful of duplicate calls, and the gold set
is small enough that it costs nothing to measure.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.embeddings.models import get_embeddings_client  # noqa: E402
from app.core.config import settings  # noqa: E402
from evaluation.harness.cached_embeddings import DEFAULT_CACHE_PATH  # noqa: E402
from evaluation.harness.runner import load_cases  # noqa: E402


async def build() -> int:
    """Embed every distinct message in the intent gold set and write the cache.

    Returns:
        Process exit code.
    """
    cases = load_cases("intents")
    # Deduplicated for the embedding calls (cheaper), but every case's message
    # is still guaranteed a cache entry since duplicates share one vector.
    texts = sorted({case.payload.get("message", "") for case in cases if case.payload.get("message")})

    client = get_embeddings_client()
    model_name = settings.OLLAMA_EMBEDDING_MODEL

    print(f"{len(texts)} benzersiz mesaj gömülüyor...")
    vectors = await client.embed_documents(texts)

    if len(vectors) != len(texts):
        print(
            f"HATA: {len(texts)} metin için {len(vectors)} vektör döndü.",
            file=sys.stderr,
        )
        return 1

    payload = {
        "model": model_name,
        "dimension": len(vectors[0]) if vectors else 0,
        "embeddings": [
            {"text": text, "vector": vector} for text, vector in zip(texts, vectors)
        ],
    }

    DEFAULT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"yazıldı: {DEFAULT_CACHE_PATH} ({len(texts)} mesaj, boyut {payload['dimension']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(build()))
