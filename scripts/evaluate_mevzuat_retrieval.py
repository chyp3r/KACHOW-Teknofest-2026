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

`--live` adds a third, independent measurement: the same ten queries sent to
mevzuat-mcp's `search_mevzuat` via `phrase` (the codebase's own query-format
change for `LOCAL_MODE=false`'s live escalation, see
`app.ai.workflows.document_analysis_graph._fetch_live_mevzuat_excerpt`) --
checking whether a topic-shaped query built for BM25 keyword density
("Resmî Yazı resmî yazışma usul esas ...") actually works as Solr `phrase`
syntax was never verified against the real service, only reasoned about.
Requires an installed mevzuat-mcp and network access; `register_servers()`
is called for it the same way `scripts/fetch_mevzuat_corpus.py` does.

Usage:
    python scripts/evaluate_mevzuat_retrieval.py
    python scripts/evaluate_mevzuat_retrieval.py --k 5
    python scripts/evaluate_mevzuat_retrieval.py --live
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
from app.mcp.mevzuat_client import resolve_mevzuat_id, search_by_phrase  # noqa: E402
from app.mcp.registry import MEVZUAT_SERVER, is_registered, register_servers  # noqa: E402
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

#: `document_tools.WEAK_SCORE_THRESHOLD`'un kalibrasyonu için: korpüsün
#: (curated 7 kanun) hiçbirinin gerçekten yanıtlamadığı, açıkça alakasız
#: sorgular. `--show-scores` bunların en iyi eşleşme skorunu, cevaplanabilir
#: sorgulardakiyle yan yana yazdırır -- eşik, bu iki dağılımın arasına
#: konmalıdır. `chat/router.py`'nin kapsam dışı örnekleriyle aynı ruhta:
#: gündelik/alakasız, mevzuat kelime dağarcığı taşımayan sorular.
UNANSWERABLE_QUERIES: list[str] = [
    "yapay zeka telif hakkı düzenlemesi",
    "kripto para vergilendirmesi",
    "trafik cezası itiraz süresi",
    "boşanma davası nafaka hesabı",
    "ihracat gümrük vergisi oranı",
]


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


async def _expected_document_id(
    law_number: str, cache: dict[str, str | None]
) -> str | None:
    """Resolve a law number to mevzuat-mcp's own document id, once per number.

    This is the "answer key" `--live`'s phrase search is checked against --
    several `DocumentType`s share the same expected law, so this is cached
    to keep the added call count to one per unique law rather than one per
    document type.
    """
    if law_number not in cache:
        cache[law_number] = await resolve_mevzuat_id(law_number, "KANUN")
    return cache[law_number]


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mevzuat getiriminin belge türüne göre doğru kanunu bulup bulmadığını ölç."
    )
    parser.add_argument("--k", type=int, default=3, help="Top-K eşik (varsayılan 3).")
    parser.add_argument(
        "--show-scores",
        action="store_true",
        help=(
            "Her sorgunun en iyi RRF skorunu yazdır ve UNANSWERABLE_QUERIES'e "
            "karşı da çalıştır -- app.ai.tools.document_tools.WEAK_SCORE_"
            "THRESHOLD'u kalibre etmek için cevaplanabilir/cevaplanamaz "
            "skor dağılımlarını yan yana verir."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Aynı 10 sorguyu mevzuat-mcp'nin `phrase` aramasına da gönder ve "
            "yerel korpusla yan yana raporla. mevzuat-mcp kurulu ve "
            "erişilebilir olmalı."
        ),
    )
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
    header = f"{'tür':20s} {'beklenen kanun':16s} {'getirilen kanunlar':30s} {'sonuç':10s}"
    if args.show_scores:
        header += " en-iyi-skor"
    print(header)
    print("-" * 88)

    hits = 0
    total = 0
    answerable_top_scores: list[float] = []
    for document_type, expected_law in EXPECTED_LAW.items():
        query = _build_query(document_type)
        documents = await retriever.retrieve(query, limit=args.k)
        retrieved_laws = [_law_of(document.metadata.get("mevzuat", "")) for document in documents]
        top_score = documents[0].metadata.get("score", 0.0) if documents else 0.0
        answerable_top_scores.append(top_score)

        precision = precision_at_k(retrieved_laws, {expected_law}, args.k)
        recall = recall_at_k(retrieved_laws, {expected_law}, args.k)
        hit = recall > 0.0
        hits += hit
        total += 1

        mark = "OK " if hit else "HATA"
        line = (
            f"{document_type.value:20s} {expected_law:16s} "
            f"{', '.join(retrieved_laws) or '(boş)':30s} {mark:10s}"
            f"(P@{args.k}={precision:.2f})"
        )
        if args.show_scores:
            line += f" {top_score:.4f}"
        print(line)

    print("-" * 88)
    print(f"İsabet: {hits}/{total} ({100 * hits / total:.1f}%)")

    if args.show_scores:
        unanswerable_top_scores: list[float] = []
        print()
        print(f"{'cevaplanamaz sorgu':45s} en-iyi-skor")
        print("-" * 88)
        for query in UNANSWERABLE_QUERIES:
            documents = await retriever.retrieve(query, limit=args.k)
            top_score = documents[0].metadata.get("score", 0.0) if documents else 0.0
            unanswerable_top_scores.append(top_score)
            print(f"{query:45s} {top_score:.4f}")

        print("-" * 88)
        print(
            "Cevaplanabilir en-iyi-skor  : "
            f"min={min(answerable_top_scores):.4f} "
            f"max={max(answerable_top_scores):.4f} "
            f"ort={sum(answerable_top_scores) / len(answerable_top_scores):.4f}"
        )
        print(
            "Cevaplanamaz en-iyi-skor    : "
            f"min={min(unanswerable_top_scores):.4f} "
            f"max={max(unanswerable_top_scores):.4f} "
            f"ort={sum(unanswerable_top_scores) / len(unanswerable_top_scores):.4f}"
        )
        print(
            "\nWEAK_SCORE_THRESHOLD (document_tools.py), iki dağılımın "
            "arasına, cevaplanamaz max'ının üzerine ve cevaplanabilir "
            "min'inin altına ya da mümkün olduğunca yakınına konmalı."
        )

    live_hits = 0
    live_total = 0
    if args.live:
        register_servers()
        if not is_registered(MEVZUAT_SERVER):
            print(
                "\nUYARI: --live istendi ama mevzuat sunucusu kayıtlı değil "
                "(MEVZUAT_MCP_ENABLED veya MEVZUAT_SOURCE=mcp gerekir); canlı "
                "ölçüm atlandı."
            )
        else:
            print()
            print("=" * 88)
            print("   Canlı mevzuat-mcp Ölçümü (phrase araması)")
            print("=" * 88)
            print(f"{'tür':20s} {'beklenen kanun':16s} {'dönen mevzuat_id':20s} {'sonuç'}")
            print("-" * 88)

            expected_id_cache: dict[str, str | None] = {}
            for document_type, expected_law in EXPECTED_LAW.items():
                query = _build_query(document_type)
                try:
                    live_document_id = await search_by_phrase(query)
                    expected_id = await _expected_document_id(
                        expected_law, expected_id_cache
                    )
                except Exception as exc:  # noqa: BLE001 -- report, don't crash the run
                    live_document_id = None
                    expected_id = None
                    print(f"    ({document_type.value}: hata -- {exc})")

                live_hit = (
                    live_document_id is not None and live_document_id == expected_id
                )
                live_hits += live_hit
                live_total += 1

                mark = "OK " if live_hit else "HATA"
                print(
                    f"{document_type.value:20s} {expected_law:16s} "
                    f"{live_document_id or '(boş)':20s} {mark}"
                )

            print("-" * 88)
            print(
                f"Canlı isabet: {live_hits}/{live_total} "
                f"({100 * live_hits / live_total:.1f}%)"
            )
            print(
                "\nDüşük isabet _build_mevzuat_query'nin ürettiği anahtar-kelime "
                "yığınının Solr `phrase` sözdizimiyle uyuşmadığını gösterir -- "
                "çözüm sırayla: sorguyu `konu` alanıyla sadeleştirmek, "
                "tamCumle/basliktaAra kombinasyonlarını denemek, ya da "
                "DOCUMENT_TYPE_QUERY_TERMS ekini phrase yolunda atlamak."
            )

    print("=" * 88)
    if args.live and live_total:
        return 0 if hits == total and live_hits == live_total else 1
    return 0 if hits == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
