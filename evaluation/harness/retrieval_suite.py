"""Measures retrieval quality across chunking configurations against the
retrieval gold set.

Deterministic and LLM-free, per ``evaluation/README.md``'s rejection of
RAGAS/LLM-as-judge (a local Ollama at ~28 tok/s would make the judge the
noisiest term in the measurement). The alternative used here: a chunk is
labelled relevant iff it contains, verbatim (after whitespace/casefold
normalisation), at least one of the gold case's ``answer_spans`` -- the
span itself is the label, and containment is checkable by string search,
no annotator and no model call required. See ``docs/evaluation/
retrieval.md`` for the full rationale and the Turkish-casefold trap this
module works around (``str.lower()`` mishandles ``İ``/``I``).

Relevance labels must be chunker-independent -- "chunk #7 is relevant"
means nothing once two configurations cut the same document into different
chunks. Answer-span containment is; it is re-evaluated against whichever
chunks a given arm actually produced.

Exercises real production retrieval code: the chunkers
(``app.ai.embeddings.chunking``), the real
``app.ai.retrieval.hybrid.HybridRetriever``, the real
``app.ai.retrieval.sparse_encoder.SparseBM25Encoder`` (unfit, per document
-- the same choice ``DocumentService._index_for_qa`` makes and for the same
reason: BM25 IDF over a corpus of one document is a constant). Only the
storage layer is stubbed, by ``evaluation.harness.in_memory_store.
InMemoryHybridStore`` -- see that module's docstring for the one thing that
makes this not a bit-for-bit measurement of the serving stack (Python RRF
vs. Qdrant's native Rust RRF).

Chunker construction is direct (``RecursiveChunker(...)``/
``SemanticChunker(...)``), never through ``get_policy()``. This suite is a
caller that supplies its own parameters to compare, the same way
``intent_suite`` binds ``resolve_plan`` with ``llm_client=None`` rather
than mutating config -- ``get_policy()`` stays the single, unauditable-by-
override source of the production default. This is a different concern
from ``DraftPolicy.style_examples_enabled``, which *is* meant as a runtime
A/B and emergency-rollback lever for production traffic; conflating the two
would make the "no reload" promise in ``app.ai.policy``'s docstring a lie
by omission.
"""

import asyncio
import re
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional
from unittest.mock import patch

from app.ai.documents.anchors import PAGE_SEPARATOR, build_page_map
from app.ai.embeddings.chunking.base import BaseChunker
from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.embeddings.chunking.semantic import SemanticChunker
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.embeddings.service import EmbeddedChunk, EmbeddingService
from app.ai.policy import get_policy
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.retrieval.reranker import CrossEncoderReranker
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from evaluation.harness.cached_embeddings import CachedEmbeddingsClient
from evaluation.harness.in_memory_store import InMemoryHybridStore
from evaluation.harness.runner import REPO_ROOT, EvalCase, EvalRun, load_cases, run_cases
from evaluation.metrics import hit_rate_at_k, mean_reciprocal_rank, ndcg_at_k, precision_at_k, recall_at_k

SUITE = "retrieval"
DATASET = "retrieval"

CORPUS_DIR = REPO_ROOT / "evaluation" / "datasets" / "retrieval_corpus"

#: Written by scripts/build_eval_embeddings.py --target retrieval. Keyed on
#: exact text like intent_embeddings.json, but the keyed texts differ: every
#: chunk each arm produces, every sentence SemanticChunker's own internal
#: sentence-boundary split needs embedded to decide where to cut, and every
#: gold-set query -- see that script's docstring for why the union across
#: every arm must be cached, not just the production baseline's chunks.
RETRIEVAL_EMBEDDINGS_PATH = (
    REPO_ROOT / "evaluation" / "datasets" / "retrieval_embeddings.json"
)

#: Matches DraftPolicy.source_chunk_count -- the headline number here
#: describes what the draft writer actually receives, not an arbitrary
#: cut-off.
DEFAULT_K = 6

#: Categories with no gold answer_spans (deliberately unanswerable
#: queries). Excluded from the precision/recall/MRR/nDCG aggregate --
#: those metrics are undefined over an empty relevant set and would just
#: contribute a meaningless 0.0 -- and scored separately via top1_score
#: (see corpus_stats below) as a spurious-confidence diagnostic instead.
UNANSWERABLE_CATEGORY = "yok"


@dataclass(frozen=True)
class ChunkingArm:
    """One chunking configuration to measure.

    Attributes:
        name: Report label. ``recursive-1500-300`` is the production
            baseline (``ChunkingPolicy.qa_chunk_size``/``qa_chunk_overlap``
            defaults -- raised from 1000/200 after this very suite measured
            1500/300 winning on every metric, see
            ``evaluation/reports/retrieval-baseline.md``); the other
            recursive arms are the parameter sweep this suite exists to
            inform. ``semantic-p85`` is an eval-only exploration arm -- see
            ``SemanticChunker``'s own docstring for why it is not wired
            into production, and why this suite is where that question
            gets an answer instead of a docstring opinion.
        build: Builds the chunker, given the embeddings client it needs
            (only ``semantic-p85`` actually uses it -- ``RecursiveChunker``
            ignores the argument).
    """

    name: str
    build: Callable[[BaseEmbeddingsClient], BaseChunker]


def _recursive_arm(name: str, chunk_size: int, chunk_overlap: int) -> ChunkingArm:
    return ChunkingArm(
        name=name,
        build=lambda _embeddings: RecursiveChunker(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        ),
    )


ARMS: dict[str, ChunkingArm] = {
    "recursive-512-128": _recursive_arm("recursive-512-128", 512, 128),
    "recursive-1000-200": _recursive_arm("recursive-1000-200", 1000, 200),
    "recursive-1500-300": _recursive_arm("recursive-1500-300", 1500, 300),
    "semantic-p85": ChunkingArm(
        name="semantic-p85",
        build=lambda embeddings: SemanticChunker(
            embeddings_client=embeddings, threshold_type="percentile", threshold_value=85.0
        ),
    ),
}

#: The arm every other arm is compared against in the report -- today's
#: actual production configuration (ChunkingPolicy's defaults). Was
#: "recursive-1000-200" until this suite's own measurement (see
#: evaluation/reports/retrieval-baseline.md) moved the production default
#: to 1500/300.
BASELINE_ARM = "recursive-1500-300"


#: Turkish-specific casefold: str.lower() alone maps 'İ' to a two-codepoint
#: 'i̇' and 'I' to plain ASCII 'i', neither of which is the Turkish
#: lowercase form ('i' and 'ı' respectively). Mapping the four dotted/
#: dotless pairs by hand first, then lower()-ing the rest, avoids both --
#: str.lower() never sees an 'İ' or 'I' left over to mis-map.
_TURKISH_UPPER_MAP = str.maketrans(
    {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ", "Ü": "ü", "Ö": "ö", "Ç": "ç"}
)
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Turkish-casefold and collapse whitespace, for span-containment checks."""
    return _WHITESPACE_RE.sub(" ", text.translate(_TURKISH_UPPER_MAP).lower()).strip()


def _contains_span(chunk_text: str, span: str) -> bool:
    return _normalize(span) in _normalize(chunk_text)


@dataclass
class _IndexedChunk:
    """One chunk, as built for one document under one arm."""

    text: str
    document: str
    page: Optional[int]


@dataclass
class CorpusStats:
    """Descriptive, retrieval-free statistics about one arm's chunking.

    These, not precision/recall, are what actually explain *why* two arms
    score differently -- they are the mechanical cause, not the symptom.

    Attributes:
        chunk_count: Total chunks across the whole corpus.
        mean_chunk_length: Mean chunk character length.
        p50_chunk_length: Median chunk character length.
        p95_chunk_length: 95th percentile chunk character length.
        page_attribution_rate: Share of chunks carrying a ``page`` number.
            Reads 1.0 for every recursive arm and 0.0 for
            ``semantic-p85`` -- SemanticChunker does not emit
            ``start_index``, so page citation is structurally impossible
            for it today (see its own docstring). This is the numeric
            proof of that claim, not an assertion of it.
        answer_span_intactness: Share of gold answer_spans that survive
            un-split inside a single chunk, computed with no retrieval
            involved at all -- purely "did the chunk boundary cut through
            the answer". The direct mechanical explanation for a
            precision/recall difference between arms.
    """

    chunk_count: int
    mean_chunk_length: float
    p50_chunk_length: float
    p95_chunk_length: float
    page_attribution_rate: float
    answer_span_intactness: float


def _load_corpus_pages(corpus_dir: Optional[Path] = None) -> dict[str, list[str]]:
    """Read every corpus document, split into pages the same way production
    extractors join them (see app.ai.documents.anchors.PAGE_SEPARATOR).

    Args:
        corpus_dir: Override for the corpus directory, for tests.
    """
    directory = corpus_dir or CORPUS_DIR
    pages_by_document: dict[str, list[str]] = {}
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        pages_by_document[path.name] = text.split(PAGE_SEPARATOR)
    return pages_by_document


async def build_indexed_chunks(
    arm: ChunkingArm,
    embeddings_client: BaseEmbeddingsClient,
    *,
    corpus_dir: Optional[Path] = None,
) -> tuple[list[EmbeddedChunk], list[_IndexedChunk]]:
    """Chunk, embed and sparse-encode the whole corpus under one arm.

    Returns:
        The chunks in the ``EmbeddedChunk`` shape ``InMemoryHybridStore``
        loads, and a parallel plain-text index used for the corpus stats
        (which need document/page bookkeeping the store itself does not
        expose).
    """
    embedded: list[EmbeddedChunk] = []
    indexed: list[_IndexedChunk] = []
    embedding_service = EmbeddingService(embeddings_client)

    for document, pages in _load_corpus_pages(corpus_dir).items():
        joined_text = PAGE_SEPARATOR.join(pages)
        chunker = arm.build(embeddings_client)
        # Same orchestration DocumentService._index_for_qa uses: the
        # chunker is a strategy handed to EmbeddingService.process_text,
        # not driven by hand -- split and embed happen together, and the
        # metadata/sparse-vector stamping below mirrors _index_for_qa's own
        # loop over the chunks it returns.
        chunks = await embedding_service.process_text(joined_text, chunker=chunker)
        if not chunks:
            continue

        page_map = build_page_map(pages)

        # Unfit on purpose, one encoder per document -- the same choice
        # DocumentService._index_for_qa makes (see that method's own
        # docstring): BM25 IDF over a corpus of one document is a constant,
        # and get_document_qa_retriever's own HybridRetriever construction
        # passes no sparse_vocab_path for exactly the same reason.
        encoder = SparseBM25Encoder()

        for chunk in chunks:
            start_index = chunk.metadata.get("start_index")
            page = page_map.page_for_offset(start_index) if start_index is not None else None
            indices, values = encoder.encode_document(chunk.text)

            metadata = dict(chunk.metadata)
            metadata["storage_path"] = document
            if page is not None:
                metadata["page"] = page

            embedded.append(
                EmbeddedChunk(
                    text=chunk.text,
                    vector=chunk.vector,
                    metadata=metadata,
                    sparse_vector={"indices": indices, "values": values},
                )
            )
            indexed.append(_IndexedChunk(text=chunk.text, document=document, page=page))

    return embedded, indexed


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(q * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _corpus_stats(indexed: list[_IndexedChunk], cases: list[EvalCase]) -> CorpusStats:
    lengths = [float(len(chunk.text)) for chunk in indexed]
    with_page = sum(1 for chunk in indexed if chunk.page is not None)

    intact_spans = 0
    total_spans = 0
    by_document: dict[str, list[_IndexedChunk]] = {}
    for chunk in indexed:
        by_document.setdefault(chunk.document, []).append(chunk)

    for case in cases:
        spans = case.expected.get("answer_spans") or []
        document = case.payload.get("document", "")
        chunks = by_document.get(document, [])
        for span in spans:
            total_spans += 1
            if any(_contains_span(chunk.text, span) for chunk in chunks):
                intact_spans += 1

    return CorpusStats(
        chunk_count=len(indexed),
        mean_chunk_length=sum(lengths) / len(lengths) if lengths else 0.0,
        p50_chunk_length=_percentile(lengths, 0.5),
        p95_chunk_length=_percentile(lengths, 0.95),
        page_attribution_rate=with_page / len(indexed) if indexed else 0.0,
        answer_span_intactness=intact_spans / total_spans if total_spans else 0.0,
    )


@contextmanager
def _rerank_enabled(candidate_count: int):
    """Monkeypatch the real, global ``RerankPolicy`` on for the duration of
    one retrieval run, and build the real ``CrossEncoderReranker``.

    Unlike the chunkers above (see this module's own docstring on why
    those are built directly, never through ``get_policy()``), reranking
    is a ``DraftPolicy.style_examples_enabled``-shaped production A/B
    lever -- this suite exists specifically to answer whether
    ``RerankPolicy.enabled`` should flip, so it measures the real
    production wiring (``app.ai.retrieval.hybrid.HybridRetriever`` reading
    ``get_policy().rerank``) rather than a parallel path of its own.
    """
    policy = get_policy()
    enabled = replace(policy, rerank=replace(policy.rerank, enabled=True))
    reranker = CrossEncoderReranker(model_name=policy.rerank.model_name)
    with patch("app.ai.retrieval.hybrid.get_policy", return_value=enabled):
        yield reranker, candidate_count


def run(
    arm_name: str,
    *,
    k: int = DEFAULT_K,
    corpus_dir: Optional[Path] = None,
    dataset_dir: Optional[Path] = None,
    cache_path: Optional[Path] = None,
    rerank: bool = False,
) -> tuple[EvalRun, CorpusStats]:
    """Run the whole retrieval gold set under one chunking arm.

    Args:
        arm_name: A key of ``ARMS``.
        k: Cut-off rank, forwarded to both the retriever's ``limit`` and
            every rank-sensitive metric scored against this run.
        corpus_dir: Override for the corpus directory, for tests.
        dataset_dir: Override for the gold-set directory, for tests (see
            ``evaluation.harness.runner.load_cases``).
        cache_path: Override for the embeddings cache file, for tests (see
            ``evaluation.harness.cached_embeddings.CachedEmbeddingsClient``).
        rerank: When True, wires the real ``CrossEncoderReranker`` (see
            ``app.ai.retrieval.reranker``) into the retriever with
            ``RerankPolicy.enabled`` monkeypatched on for this run's
            duration -- see ``_rerank_enabled``. Loads the real
            ``sentence-transformers`` model on first use (network access
            and ``sentence-transformers``/``torch`` installed required);
            False (the default) never imports either.

    Returns:
        The completed run and the arm's corpus statistics.

    Raises:
        KeyError: For an unknown arm name.
        RuntimeError: When the embeddings cache is missing an entry --
            rerun ``scripts/build_eval_embeddings.py --target retrieval``.
    """
    arm = ARMS[arm_name]
    embeddings_client = CachedEmbeddingsClient(cache_path=cache_path or RETRIEVAL_EMBEDDINGS_PATH)

    embedded_chunks, indexed_chunks = asyncio.run(
        build_indexed_chunks(arm, embeddings_client, corpus_dir=corpus_dir)
    )

    collection_name = f"retrieval_eval::{arm.name}"
    store = InMemoryHybridStore()
    store.load(collection_name, embedded_chunks)

    by_document: dict[str, list[_IndexedChunk]] = {}
    for chunk in indexed_chunks:
        by_document.setdefault(chunk.document, []).append(chunk)

    def _decide_with(retriever: HybridRetriever) -> Callable[[EvalCase], dict[str, Any]]:
        def decide(case: EvalCase) -> dict[str, Any]:
            query = case.payload.get("query", "")
            document = case.payload.get("document", "")
            spans = case.expected.get("answer_spans") or []

            results = asyncio.run(
                retriever.retrieve(query, limit=k, filter_dict={"storage_path": document})
            )
            retrieved_ids = [doc.page_content for doc in results]
            retrieved_scores = [doc.metadata.get("score", 0.0) for doc in results]
            relevant_ids = [
                chunk.text
                for chunk in by_document.get(document, [])
                if any(_contains_span(chunk.text, span) for span in spans)
            ]

            return {
                "retrieved_ids": retrieved_ids,
                "relevant_ids": relevant_ids,
                "top1_score": retrieved_scores[0] if retrieved_scores else 0.0,
            }

        return decide

    cases = load_cases(DATASET, dataset_dir=dataset_dir)

    with _rerank_enabled(get_policy().rerank.candidate_count) if rerank else nullcontext(
        (None, None)
    ) as (reranker, _candidate_count):
        retriever = HybridRetriever(
            vector_store=store,
            embeddings_client=embeddings_client,
            collection_name=collection_name,
            reranker=reranker,
        )
        run_result = run_cases(
            f"{SUITE}::{arm_name}", DATASET, cases, _decide_with(retriever)
        )

    stats = _corpus_stats(indexed_chunks, cases)
    return run_result, stats


def to_metrics(run_result: EvalRun, *, k: int = DEFAULT_K) -> dict[str, Any]:
    """Score a completed run into precision/recall/MRR/nDCG plus the
    yok-category spurious-confidence diagnostic.

    "yok" cases (no gold answer_spans -- see UNANSWERABLE_CATEGORY) are
    excluded from the ranking metrics, which are undefined over an empty
    relevant set, and scored separately as mean_yok_top1_score instead: a
    configuration that returns high-confidence hits for a question the
    corpus never answers is a real failure mode precision/recall cannot
    see.

    Args:
        run_result: A completed run from ``run``.
        k: Cut-off rank the metrics are computed at.

    Returns:
        The scored summary.
    """
    answerable = [
        result for result in run_result.results if result.case.category != UNANSWERABLE_CATEGORY
    ]
    unanswerable = [
        result for result in run_result.results if result.case.category == UNANSWERABLE_CATEGORY
    ]

    rankings = [
        (result.observed["retrieved_ids"], result.observed["relevant_ids"])
        for result in answerable
    ]

    precisions = [
        precision_at_k(result.observed["retrieved_ids"], result.observed["relevant_ids"], k)
        for result in answerable
    ]
    recalls = [
        recall_at_k(result.observed["retrieved_ids"], result.observed["relevant_ids"], k)
        for result in answerable
    ]
    hits = [
        hit_rate_at_k(result.observed["retrieved_ids"], result.observed["relevant_ids"], k)
        for result in answerable
    ]
    ndcgs = [
        ndcg_at_k(result.observed["retrieved_ids"], result.observed["relevant_ids"], k)
        for result in answerable
    ]

    return {
        "cases": len(run_result.results),
        "answerable_cases": len(answerable),
        "unanswerable_cases": len(unanswerable),
        "precision_at_k": sum(precisions) / len(precisions) if precisions else 0.0,
        "recall_at_k": sum(recalls) / len(recalls) if recalls else 0.0,
        "hit_rate_at_k": sum(hits) / len(hits) if hits else 0.0,
        "mean_reciprocal_rank": mean_reciprocal_rank(rankings),
        "ndcg_at_k": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        "mean_yok_top1_score": (
            sum(result.observed.get("top1_score", 0.0) for result in unanswerable)
            / len(unanswerable)
            if unanswerable
            else 0.0
        ),
    }


def by_category_metrics(run_result: EvalRun, *, k: int = DEFAULT_K) -> dict[str, dict[str, Any]]:
    """Same scoring as ``to_metrics``, broken down per gold-set category.

    An overall average hides exactly the category-specific failure each
    category was written to expose -- e.g. a configuration can score well
    on ``tek_cumle`` while ``paragraf_arasi`` (the chunk-boundary stress
    case) quietly falls apart.
    """
    categories: dict[str, dict[str, Any]] = {}
    for category, results in run_result.by_category().items():
        subset = EvalRun(suite=run_result.suite, dataset=run_result.dataset, results=results)
        categories[category] = to_metrics(subset, k=k)
    return categories
