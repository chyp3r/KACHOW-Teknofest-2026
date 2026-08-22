"""Guards the retrieval suite's two riskiest pieces: the Turkish span
matcher (a silent mislabel here would corrupt every relevance judgement)
and the in-memory hybrid store's fusion ranking (a silent bug here would
corrupt every retrieved-vs-relevant comparison). A final end-to-end test
proves every chunking arm, including the semantic exploration arm, wires
together against fixture data with no real Qdrant/Ollama involved -- the
same offline guarantee `make eval-retrieval` depends on.
"""

import json

import pytest
from langchain_core.documents import Document

from evaluation.harness.in_memory_store import InMemoryHybridStore
from evaluation.harness.retrieval_suite import _contains_span, _normalize, build_indexed_chunks, run
from tests.conftest import FakeEmbeddingsClient


# ==========================================
# Turkish span matcher
# ==========================================


def test_normalize_maps_turkish_dotted_and_dotless_i_correctly():
    """str.lower() alone gets both wrong: 'İ' -> two-codepoint 'i̇' instead
    of plain 'i', and 'I' -> plain ASCII 'i' instead of dotless 'ı'. A query
    built around "İZİN" (proper Turkish caps for "izin") must still match a
    chunk spelled "izin"; "IVEDİ" -- note the plain ASCII I, as OCR/typed
    text commonly produces instead of the correct İ -- must normalize to
    dotless "ıvedi", not collapse onto dotted "ivedi"."""
    assert _normalize("İZİN") == "izin"
    assert _normalize("İZİN") == _normalize("izin")
    assert _normalize("IVEDİ") == "ıvedi"
    assert _normalize("İstanbul") == "istanbul"
    assert _normalize("ISPARTA") == "ısparta"


def test_normalize_collapses_whitespace():
    assert _normalize("12 Mart   2026\ntarihinden") == _normalize("12 Mart 2026 tarihinden")


def test_contains_span_matches_regardless_of_case_and_whitespace():
    chunk = "Görevlendirme, 12 Mart 2026\ntarihinden İTİBAREN geçerlidir."
    assert _contains_span(chunk, "12 mart 2026 tarihinden itibaren")
    assert not _contains_span(chunk, "15 Nisan 2026 tarihinden itibaren")


def test_contains_span_is_a_substring_check_not_a_token_overlap():
    """A span split across two sentences must NOT match -- containment is
    literal, on purpose (see the suite's module docstring): a token-overlap
    or fuzzy match here would silently relabel a split answer as intact."""
    chunk = "Birinci cümle burada biter. İkinci cümle ise burada başlar."
    assert not _contains_span(chunk, "burada biter. İkinci cümle ise burada başlar ve devam eder")


# ==========================================
# InMemoryHybridStore
# ==========================================


@pytest.mark.asyncio
async def test_hybrid_search_ranks_the_double_winner_first():
    """Hand-computed, and true for any k: a point ranked #1 on both the
    dense and the sparse list must fuse to rank #1 overall -- its RRF score
    (2/(k+1)) is the maximum any point can reach, since every other point's
    two per-list terms are each at most 1/(k+1). Points appearing on only
    one list must still surface, ranked behind it."""
    store = InMemoryHybridStore()
    store.load(
        "col",
        [
            _fake_chunk("double_winner", vector=[1.0, 0.0], sparse={1: 10.0}),
            _fake_chunk("dense_only", vector=[0.9, 0.1], sparse={}),
            _fake_chunk("sparse_only", vector=[0.0, 1.0], sparse={1: 5.0}),
        ],
    )

    hits = await store.hybrid_search(
        "col", query_vector=[1.0, 0.0], sparse_indices=[1], sparse_values=[1.0], limit=3
    )

    ranked_texts = [hit["text"] for hit in hits]
    assert ranked_texts[0] == "double_winner"
    assert set(ranked_texts) == {"double_winner", "dense_only", "sparse_only"}


@pytest.mark.asyncio
async def test_hybrid_search_respects_the_storage_path_filter():
    """Mirrors production's document-scoped retrieval (retrieve_source_chunks_node
    filters by storage_path) -- a point from a different document must never
    leak into another document's results."""
    store = InMemoryHybridStore()
    store.load(
        "col",
        [
            _fake_chunk("doc_a_chunk", vector=[1.0, 0.0], sparse={}, storage_path="a.md"),
            _fake_chunk("doc_b_chunk", vector=[1.0, 0.0], sparse={}, storage_path="b.md"),
        ],
    )

    hits = await store.hybrid_search(
        "col", query_vector=[1.0, 0.0], sparse_indices=[], sparse_values=[], limit=5,
        filter_dict={"storage_path": "a.md"},
    )

    assert [hit["text"] for hit in hits] == ["doc_a_chunk"]


@pytest.mark.asyncio
async def test_hybrid_search_returns_nothing_for_an_unknown_collection():
    store = InMemoryHybridStore()
    hits = await store.hybrid_search("nope", query_vector=[1.0], sparse_indices=[], sparse_values=[])
    assert hits == []


def _fake_chunk(text, *, vector, sparse, storage_path="doc.md"):
    from app.ai.embeddings.service import EmbeddedChunk

    indices, values = list(sparse.keys()), list(sparse.values())
    return EmbeddedChunk(
        text=text,
        vector=vector,
        metadata={"storage_path": storage_path},
        sparse_vector={"indices": indices, "values": values},
    )


# ==========================================
# End-to-end: every arm against fixture data
# ==========================================


class _RecordingFakeEmbeddingsClient(FakeEmbeddingsClient):
    """FakeEmbeddingsClient plus a record of every text embedded, so a tiny
    fixture cache can be built without hand-enumerating which chunks and
    sentences each arm produces -- same technique
    scripts/build_eval_embeddings.py uses against the real corpus."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded: dict[str, list[float]] = {}

    async def embed_query(self, text: str) -> list[float]:
        vector = await super().embed_query(text)
        self.recorded[text] = vector
        return vector

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = await super().embed_documents(texts)
        for text, vector in zip(texts, vectors):
            self.recorded[text] = vector
        return vectors


@pytest.fixture
def fixture_corpus(tmp_path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "evrak.md").write_text(
        "Birinci sayfa metni burada başlar ve birkaç cümle içerir. "
        "Bu sayfada 12 Mart 2026 tarihi geçmektedir ve önemlidir.\n\n"
        "İkinci sayfa farklı bir konuya değinir. Bu sayfada ayrı bir "
        "tarih olan 5 Mayıs 2026 tarihi geçmektedir.",
        encoding="utf-8",
    )
    return corpus_dir


@pytest.fixture
def fixture_dataset_dir(tmp_path):
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    rows = [
        {
            "id": "fx-001",
            "category": "tek_cumle",
            "document": "evrak.md",
            "query": "Birinci sayfadaki tarih nedir?",
            "expected": {"answer_spans": ["12 Mart 2026 tarihi"], "page": 1},
        },
        {
            "id": "fx-002",
            "category": "yok",
            "document": "evrak.md",
            "query": "Belgede bahsedilmeyen bir şey nedir?",
            "expected": {"answer_spans": [], "page": None},
        },
    ]
    (dataset_dir / "retrieval.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return dataset_dir


@pytest.fixture
def fixture_cache_path(tmp_path, fixture_corpus, fixture_dataset_dir):
    """Builds a real, self-consistent embeddings cache for the fixture
    corpus and gold set, the same way scripts/build_eval_embeddings.py
    builds the real one -- run every arm's chunking through a recording
    fake client, then embed every gold-set query, then write the cache.

    A plain sync fixture, and only consumed by sync tests below: like
    intent_suite.decide, retrieval_suite.run() is itself a sync function
    that calls asyncio.run() internally (see its own body), so it can only
    be called from a context with no event loop already running -- an
    async test (or an async fixture under pytest-asyncio's asyncio_mode =
    "auto") would collide with that.
    """
    import asyncio

    from evaluation.harness.retrieval_suite import ARMS
    from evaluation.harness.runner import load_cases

    async def _build() -> dict[str, list[float]]:
        client = _RecordingFakeEmbeddingsClient()
        for arm in ARMS.values():
            await build_indexed_chunks(arm, client, corpus_dir=fixture_corpus)

        cases = load_cases("retrieval", dataset_dir=fixture_dataset_dir)
        queries = [case.payload["query"] for case in cases]
        await client.embed_documents(queries)
        return client.recorded

    recorded = asyncio.run(_build())

    cache_path = tmp_path / "retrieval_embeddings.json"
    texts = sorted(recorded)
    payload = {
        "model": "fake",
        "dimension": len(recorded[texts[0]]) if texts else 0,
        "embeddings": [{"text": text, "vector": recorded[text]} for text in texts],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cache_path


@pytest.mark.parametrize(
    "arm_name",
    ["recursive-512-128", "recursive-1000-200", "recursive-1500-300", "semantic-p85"],
)
def test_every_arm_produces_a_non_empty_run_against_fixture_data(
    arm_name, fixture_corpus, fixture_dataset_dir, fixture_cache_path
):
    """No real Qdrant/Ollama anywhere in this call graph -- proves the
    wiring (chunker -> EmbeddingService -> sparse encoder ->
    InMemoryHybridStore -> HybridRetriever -> metrics) holds for every arm,
    including the semantic exploration arm, which is the one most likely to
    silently produce zero chunks (an empty split_text result) if its
    sentence-boundary logic ever regresses."""
    run_result, stats = run(
        arm_name,
        corpus_dir=fixture_corpus,
        dataset_dir=fixture_dataset_dir,
        cache_path=fixture_cache_path,
    )

    assert len(run_result.results) == 2
    assert stats.chunk_count > 0

    tek_cumle = next(r for r in run_result.results if r.case.id == "fx-001")
    assert tek_cumle.observed["retrieved_ids"], "expected at least one retrieved chunk"


def test_semantic_arm_produces_chunks_without_page_attribution(
    fixture_corpus, fixture_dataset_dir, fixture_cache_path
):
    """Numeric proof, on fixture data, of the claim SemanticChunker's own
    docstring and ChunkingPolicy make: it does not emit start_index, so
    page attribution is structurally 0.0 -- unlike every recursive arm."""
    _, semantic_stats = run(
        "semantic-p85",
        corpus_dir=fixture_corpus,
        dataset_dir=fixture_dataset_dir,
        cache_path=fixture_cache_path,
    )
    _, recursive_stats = run(
        "recursive-1000-200",
        corpus_dir=fixture_corpus,
        dataset_dir=fixture_dataset_dir,
        cache_path=fixture_cache_path,
    )

    assert semantic_stats.page_attribution_rate == 0.0
    assert recursive_stats.page_attribution_rate == 1.0
