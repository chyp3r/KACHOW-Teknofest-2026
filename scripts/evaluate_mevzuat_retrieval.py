"""Measure whether legislation retrieval surfaces the right law per document type.

Turns the "6/6" figure recorded in CHANGELOG.md's 1.35.0 entry into a
regression-guarded number rather than a one-off measurement left in prose.
That entry compared three query-construction strategies (a fixed suffix, no
suffix, per-type terms) against the same six document types this script
still exercises, plus the four added since (`CIRCULAR`, `DIRECTIVE`,
`MINUTES`, `REPORT` -- all sharing `OFFICIAL_LETTER`'s expected law, RYUEHY,
since `DOCUMENT_TYPE_QUERY_TERMS` gives them near-identical query terms).

For each of the ten `DocumentType` values, builds the same query
`_build_mevzuat_query` (`document_analysis_graph.py`) would build from a
bare type + label (no `konu`, since this measures the type-driven query
alone), retrieves the configured legislation source, and checks whether the
document type's expected law appears among the top-K results.

No LLM call -- purely retrieval -- but it needs Qdrant, so this lives in the
script tier, not `evaluation/harness/` (`make eval` must stay `--no-deps`;
see that suite's own comment in the Makefile). Always measures the
committed local corpus via `HybridRetriever` directly, the same corpus the
original 6/6 measurement in CHANGELOG.md's 1.35.0 entry was against --
`MEVZUAT_SOURCE=mcp`'s live-fetch path is a *fallback chain* over this same
corpus (`app.ai.retrieval.mcp_mevzuat`), not a different one, so measuring
the corpus directly is what stays reproducible without a network
round-trip to mevzuat.gov.tr.

Usage:
    python scripts/evaluate_mevzuat_retrieval.py
    python scripts/evaluate_mevzuat_retrieval.py --k 5
"""

import argparse
import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.compliance import DOCUMENT_TYPE_LABELS, DOCUMENT_TYPE_QUERY_TERMS  # noqa: E402
from app.ai.embeddings.models import get_embeddings_client  # noqa: E402
from app.ai.retrieval.hybrid import HybridRetriever  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.enums.document_type import DocumentType  # noqa: E402
from app.infrastructure.vectorstore import get_vector_store  # noqa: E402
from evaluation.metrics import precision_at_k, recall_at_k  # noqa: E402

#: Every DocumentType's naturally-governing law, by number -- the ground
#: truth this script checks retrieval against. Types sharing a governing
#: regulation (the five official-correspondence-shaped types, all governed
#: by RYUEHY) are expected to agree; this is not an oversight, it mirrors
#: REQUIRED_FIELD_RULES's own grouping (field_rule.py) where the same five
#: types share _OFFICIAL_HEADER_RULES.
EXPECTED_LAW: dict[DocumentType, str] = {
    DocumentType.OFFICIAL_LETTER: "2646",
    DocumentType.CIRCULAR: "2646",
    DocumentType.DIRECTIVE: "2646",
    DocumentType.MINUTES: "2646",
    DocumentType.REPORT: "2646",
    DocumentType.OTHER: "2646",
    DocumentType.PETITION: "3071",
    DocumentType.COMPLAINT: "3071",
    DocumentType.INFORMATION_REQUEST: "4982",
    DocumentType.LEAVE_REQUEST: "657",
}

#: Law number -> folded title substring, used to recognise which law a
#: retrieved excerpt's `metadata["mevzuat"]` belongs to without importing
#: `app.ai.compliance.mevzuat_citation`'s private title table directly.
LAW_TITLE_SUBSTRING: dict[str, str] = {
    "2646": "Resmî Yazışmalarda",
    "3071": "Dilekçe Hakkının",
    "4982": "Bilgi Edinme Hakkı",
    "657": "Devlet Memurları",
}


def _build_query(document_type: DocumentType) -> str:
    """Mirror `_build_mevzuat_query`'s type-driven half (no `konu` term)."""
    label = DOCUMENT_TYPE_LABELS[document_type]
    terms = DOCUMENT_TYPE_QUERY_TERMS[document_type]
    return f"{label} {terms}".strip()


def _law_of(mevzuat_title: str) -> str:
    for number, substring in LAW_TITLE_SUBSTRING.items():
        if substring in mevzuat_title:
            return number
    return "?"


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mevzuat getiriminin belge türüne göre doğru kanunu bulup bulmadığını ölç."
    )
    parser.add_argument("--k", type=int, default=3, help="Top-K eşik (varsayılan 3).")
    args = parser.parse_args()

    retriever = HybridRetriever(
        vector_store=get_vector_store(),
        embeddings_client=get_embeddings_client(),
        collection_name=settings.MEVZUAT_COLLECTION_NAME,
        sparse_vocab_path=os.path.join(settings.MEVZUAT_CORPUS_DIR, "sparse_vocab.json"),
    )

    print("=" * 88)
    print("   Mevzuat Getirimi Değerlendirmesi")
    print("=" * 88)
    print(f"MEVZUAT_SOURCE : {settings.MEVZUAT_SOURCE}")
    print(f"Top-K          : {args.k}\n")
    print(f"{'tür':20s} {'beklenen kanun':16s} {'getirilen kanunlar':30s} {'sonuç'}")
    print("-" * 88)

    hits = 0
    total = 0
    for document_type, expected_law in EXPECTED_LAW.items():
        query = _build_query(document_type)
        documents = await retriever.retrieve(query, limit=args.k)
        retrieved_laws = [_law_of(document.metadata.get("mevzuat", "")) for document in documents]

        precision = precision_at_k(retrieved_laws, {expected_law}, args.k)
        recall = recall_at_k(retrieved_laws, {expected_law}, args.k)
        hit = recall > 0.0
        hits += hit
        total += 1

        mark = "OK " if hit else "HATA"
        print(
            f"{document_type.value:20s} {expected_law:16s} "
            f"{', '.join(retrieved_laws) or '(boş)':30s} {mark} "
            f"(P@{args.k}={precision:.2f})"
        )

    print("-" * 88)
    print(f"İsabet: {hits}/{total} ({100 * hits / total:.1f}%)")
    print("=" * 88)
    return 0 if hits == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
