"""Precomputes the semantic prototype vectors into datasets/prototypes/.

Run once after changing ``app/ai/policy/prototypes.py``, the embedding model, or
``POLICY_VERSION``:

    docker compose run --rm --no-deps backend python scripts/build_prototypes.py

Precomputing is the point of the whole layer. Embedding ~30 prototype phrases at
request time would cost more than the fast-tier model call the layer exists to
avoid; the runtime path embeds exactly one string, the user's own message.

Every file is stamped with the embedding model, its dimension and the policy
version. The matcher refuses to load a file whose stamp does not match the
running configuration -- deciding from vectors built by a different model is
worse than paying for a model call, because it is confidently wrong rather than
merely slow.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.embeddings.models import get_embeddings_client  # noqa: E402
from app.ai.policy import POLICY_VERSION  # noqa: E402
from app.ai.policy.prototypes import FAMILIES, prototype_texts  # noqa: E402
from app.ai.semantic.prototype_matcher import PROTOTYPE_DIR  # noqa: E402
from app.core.config import settings  # noqa: E402


async def build() -> int:
    """Embed every family's prototypes and write them to disk.

    Returns:
        Process exit code.
    """
    client = get_embeddings_client()
    model_name = settings.OLLAMA_EMBEDDING_MODEL
    PROTOTYPE_DIR.mkdir(parents=True, exist_ok=True)

    for family in FAMILIES:
        pairs = prototype_texts(family)
        texts = [text for _label, text in pairs]

        print(f"[{family}] {len(texts)} prototip gömülüyor...")
        vectors = await client.embed_documents(texts)

        if len(vectors) != len(pairs):
            print(
                f"[{family}] HATA: {len(pairs)} metin için {len(vectors)} vektör döndü.",
                file=sys.stderr,
            )
            return 1

        payload = {
            "family": family,
            "model": model_name,
            "dimension": len(vectors[0]) if vectors else 0,
            "policy_version": POLICY_VERSION,
            "prototypes": [
                {"label": label, "text": text, "vector": vector}
                for (label, text), vector in zip(pairs, vectors)
            ],
        }

        path = PROTOTYPE_DIR / f"{family}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"[{family}] yazıldı: {path} (boyut {payload['dimension']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(build()))
