"""Operation-count regression guards: no infra, no wall clock, no flake.

Workstream E's own split (see the approved plan): wall-clock benchmarks vary
3-5x between a laptop and a CI runner and make a bad gate that either flakes
or is set so loose it never catches anything. A *count* of LLM calls,
embedding batches, retrieval round-trips, or chunks is hardware-independent
and exactly as sensitive to the regressions that actually matter -- an extra
retry loop, a batch call turned into a per-item loop, a chunker that started
producing 3x the chunks. Millisecond-scale and infra-free by construction
(``FakeLLMClient``/``FakeEmbeddingsClient`` and call-counting retriever
stubs, never real Qdrant/Postgres/Ollama), so unlike the rest of
``tests/performance/`` this file is not deselected by ``addopts`` -- it runs
in the default `make test` lane too.
"""

from typing import Any

import pytest

from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.embeddings.service import EmbeddingService
from app.ai.policy import get_policy
from app.ai.workflows.draft_graph import create_draft_graph
from app.core.config import settings

#: Deliberately NOT `pytest.mark.performance` -- that marker is what
#: pyproject.toml's `addopts` deselects from the default lane, and this
#: file's whole point (per the module docstring above) is running in it.
#: Living in tests/performance/ is organizational only.

SOURCE_DOCUMENT = "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak."

GOOD_DRAFT = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

DRAFT_STATE = {
    "source_document": SOURCE_DOCUMENT,
    "document_id": "uploads/perf-test-doc.pdf",
    "classification": {
        "document_type_label": "Resmî Yazı",
        "summary": "Test evrakı.",
        "fields": {},
        "missing_fields": [],
    },
    "correspondence_type": "cover_letter",
    "context": "İlgili mevzuat metni burada.",
    "instructions": "Test talimatı.",
}


class _CountingRetriever:
    """A minimal stand-in for ExampleRetriever/HybridRetriever that only counts."""

    def __init__(self) -> None:
        self.call_count = 0

    async def retrieve(self, *args: Any, **kwargs: Any) -> list:
        self.call_count += 1
        return []


@pytest.fixture(autouse=True)
def _disable_judge(monkeypatch):
    """Isolates the call-count assertions from the judge's own optional call.

    Same rationale/pattern as ``test_draft_loop.py``'s identical fixture --
    the judge is a separate, already-covered concern (``test_llm_judge.py``),
    not what this file's counts are about.
    """
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)


@pytest.mark.asyncio
async def test_a_clean_draft_run_calls_the_llm_exactly_once(fake_llm, fake_fast_llm):
    """No repair pass, no judge: the writer's single streamed pass is the
    only LLM call a clean draft should ever cost.

    A regression here (an accidental extra retry, a redundant re-verify call
    that hits the model, a repair loop firing on a draft that needed none)
    silently doubles the per-draft latency and Ollama load without any unit
    test noticing, since most of them mock at the agent level, not the
    client level -- this counts the actual ``BaseLLMClient`` calls both
    reasoning tiers make combined, whichever tier the writer's preset
    resolves to.
    """
    fake_llm.stream_chunks = [GOOD_DRAFT]
    fake_fast_llm.stream_chunks = [GOOD_DRAFT]
    graph = create_draft_graph(fake_llm, fast_llm_client=fake_fast_llm)

    result = await graph.ainvoke(DRAFT_STATE)

    assert result["status"] == "COMPLETED"
    total_llm_calls = (
        len(fake_llm.stream_calls)
        + len(fake_llm.generate_calls)
        + len(fake_llm.generate_structured_calls)
        + len(fake_fast_llm.stream_calls)
        + len(fake_fast_llm.generate_calls)
        + len(fake_fast_llm.generate_structured_calls)
    )
    assert total_llm_calls == 1


@pytest.mark.asyncio
async def test_a_draft_run_makes_exactly_two_retrieval_round_trips(fake_llm):
    """``retrieve_examples`` + ``retrieve_source_chunks`` -- never more.

    Both are optional, best-effort lookups (see their own node docstrings in
    ``draft_graph.py``); this guards against either one silently turning
    into a loop (e.g. a per-field query instead of one combined query) --
    each extra round trip is a real Qdrant network call multiplied across
    every draft this system generates.
    """
    fake_llm.stream_chunks = [GOOD_DRAFT]
    example_retriever = _CountingRetriever()
    document_qa_retriever = _CountingRetriever()
    graph = create_draft_graph(
        fake_llm,
        example_retriever=example_retriever,
        document_qa_retriever=document_qa_retriever,
    )

    await graph.ainvoke(DRAFT_STATE)

    assert example_retriever.call_count == 1
    assert document_qa_retriever.call_count == 1


@pytest.mark.asyncio
async def test_a_document_s_chunks_are_embedded_in_a_single_batch_call(fake_embeddings):
    """``EmbeddingService.process_text`` must issue one ``embed_documents``
    call for the whole document, never one call per chunk.

    A per-chunk loop would still pass every functional test (the returned
    vectors are identical either way) while silently multiplying Ollama
    round-trips by the chunk count -- exactly the kind of regression a
    correctness test can't see and this one exists to catch.
    """
    text = "Paragraf metni. " * 200  # long enough to force multiple chunks
    chunker = RecursiveChunker(chunk_size=200, chunk_overlap=40)
    service = EmbeddingService(embeddings_client=fake_embeddings)

    chunks = await service.process_text(text, chunker=chunker)

    assert len(chunks) > 1, "test setup didn't actually produce multiple chunks"
    assert len(fake_embeddings.embed_documents_calls) == 1
    assert len(fake_embeddings.embed_documents_calls[0]) == len(chunks)


def _fixed_50kb_text() -> str:
    unit = (
        "Bu bir test cümlesidir ve tekrar tekrar yazılarak elli kilobayt "
        "büyüklüğünde bir metin oluşturmak için kullanılır. "
    )
    return (unit * (50_000 // len(unit) + 1))[:50_000]


@pytest.mark.asyncio
async def test_chunk_count_for_a_fixed_50kb_input_is_pinned_per_strategy():
    """A regression guard on ``RecursiveChunker`` itself, not on the policy
    values (those are Workstream A's own concern, ``test_policy.py``).

    Pinned to the counts measured against a fixed 50KB input under today's
    committed ``ChunkingPolicy`` values (1500/300 for qa, 1000/200 for
    mevzuat) -- a deliberate change to either the chunker's splitting logic
    or those policy defaults should fail this test and force an explicit,
    reviewed update, not silently change how many chunks (and therefore how
    many embedding calls and how much Qdrant storage) every future upload
    costs.
    """
    text = _fixed_50kb_text()
    policy = get_policy().chunking

    qa_chunker = RecursiveChunker(chunk_size=policy.qa_chunk_size, chunk_overlap=policy.qa_chunk_overlap)
    mevzuat_chunker = RecursiveChunker(
        chunk_size=policy.mevzuat_chunk_size, chunk_overlap=policy.mevzuat_chunk_overlap
    )

    qa_chunks = await qa_chunker.split_text(text)
    mevzuat_chunks = await mevzuat_chunker.split_text(text)

    assert len(qa_chunks) == 42
    assert len(mevzuat_chunks) == 62
