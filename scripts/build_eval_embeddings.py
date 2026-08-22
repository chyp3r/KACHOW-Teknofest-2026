"""Precomputes embeddings for the intent gold set or the retrieval gold set.

Run once after editing the relevant gold set:

    docker compose run --rm --no-deps backend python scripts/build_eval_embeddings.py
    docker compose run --rm --no-deps backend python scripts/build_eval_embeddings.py --target retrieval

Mirrors ``scripts/build_prototypes.py``'s reasoning exactly: ``make eval``
embeds nothing at request time, so measuring the semantic rung
(``app.ai.semantic.prototype_matcher``) or the retrieval suite
(``evaluation.harness.retrieval_suite``) against their real gold sets needs
the relevant text embedded once, offline, and cached -- see
``evaluation.harness.cached_embeddings.CachedEmbeddingsClient``, which reads
either target's output and never calls a model.

Every message/text is embedded (not deduplicated against what's already
cached first): this always re-embeds the current gold set from scratch
rather than diffing against a prior cache, and a stable, indexable file
keyed by exact text is worth the handful of duplicate calls -- both gold
sets are small enough that it costs nothing to measure.

The ``--target retrieval`` path cannot just embed chunk texts. It runs the
real chunking pipeline for every ``evaluation.harness.retrieval_suite.ARMS``
entry through a recording embeddings client, so every text a live run would
ever need to look up gets captured: not only each arm's resulting chunks,
but also the sentence-level texts ``SemanticChunker``'s own internal
sentence-boundary splitting needs embedded to decide where to cut (see that
class's docstring) -- ``retrieval_suite.run`` reconstructs the same chunker
at eval time against the *cached* client, and a cache miss there is a loud
``KeyError``, not a silent degrade. Recording every text actually embedded
during a real run is more robust than hand-enumerating "chunks plus
sentences plus queries" separately, and stays correct if a chunker's
internal embedding granularity ever changes.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.embeddings.models import BaseEmbeddingsClient, get_embeddings_client  # noqa: E402
from app.core.config import settings  # noqa: E402
from evaluation.harness.cached_embeddings import DEFAULT_CACHE_PATH  # noqa: E402
from evaluation.harness.runner import load_cases  # noqa: E402


class _RecordingEmbeddingsClient(BaseEmbeddingsClient):
    """Wraps a real embeddings client and records every (text, vector) pair
    it is ever asked to embed, regardless of which method or call site asked
    for it. See this module's docstring for why recording beats enumerating."""

    def __init__(self, inner: BaseEmbeddingsClient) -> None:
        self.inner = inner
        self.recorded: Dict[str, List[float]] = {}

    async def embed_query(self, text: str) -> List[float]:
        vector = await self.inner.embed_query(text)
        self.recorded[text] = vector
        return vector

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vectors = await self.inner.embed_documents(texts)
        for text, vector in zip(texts, vectors):
            self.recorded[text] = vector
        return vectors


def _write_cache(path: Path, model_name: str, recorded: Dict[str, List[float]]) -> None:
    texts = sorted(recorded)
    payload = {
        "model": model_name,
        "dimension": len(recorded[texts[0]]) if texts else 0,
        "embeddings": [{"text": text, "vector": recorded[text]} for text in texts],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"yazıldı: {path} ({len(texts)} metin, boyut {payload['dimension']})")


async def _build_intents(model_name: str) -> int:
    """Embed every distinct message in the intent gold set."""
    cases = load_cases("intents")
    texts = sorted({case.payload.get("message", "") for case in cases if case.payload.get("message")})

    client = get_embeddings_client()
    print(f"{len(texts)} benzersiz mesaj gömülüyor...")
    vectors = await client.embed_documents(texts)

    if len(vectors) != len(texts):
        print(f"HATA: {len(texts)} metin için {len(vectors)} vektör döndü.", file=sys.stderr)
        return 1

    _write_cache(DEFAULT_CACHE_PATH, model_name, dict(zip(texts, vectors)))
    return 0


async def _build_retrieval(model_name: str) -> int:
    """Chunk the retrieval corpus under every arm, recording every text any
    of them embeds along the way, then embed every gold-set query too."""
    # Imported lazily: retrieval_suite imports InMemoryHybridStore, which
    # imports app.ai.retrieval.fusion -- no reason to pay that import cost
    # for a plain --target intents run.
    from evaluation.harness import retrieval_suite

    client = _RecordingEmbeddingsClient(get_embeddings_client())

    for arm_name, arm in retrieval_suite.ARMS.items():
        print(f"'{arm_name}' koluyla korpus parçalanıyor ve gömülüyor...")
        await retrieval_suite.build_indexed_chunks(arm, client)

    cases = load_cases(retrieval_suite.DATASET)
    queries = sorted({case.payload.get("query", "") for case in cases if case.payload.get("query")})
    print(f"{len(queries)} sorgu gömülüyor...")
    await client.embed_documents(queries)

    _write_cache(retrieval_suite.RETRIEVAL_EMBEDDINGS_PATH, model_name, client.recorded)
    return 0


async def build(target: str) -> int:
    """Dispatch to the target's build routine and write its cache.

    Args:
        target: ``"intents"`` or ``"retrieval"``.

    Returns:
        Process exit code.
    """
    model_name = settings.OLLAMA_EMBEDDING_MODEL
    if target == "intents":
        return await _build_intents(model_name)
    if target == "retrieval":
        return await _build_retrieval(model_name)
    raise ValueError(f"Unknown target: {target}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("intents", "retrieval"), default="intents")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(build(_parse_args().target)))
