"""Wall-clock micro-benchmarks for pure-CPU, I/O-free hot paths.

Deliberately separate from ``test_operation_counts.py`` (see this repo's own
plan/docs/evaluation approach to why): a *count* is hardware-independent and
belongs in the default lane; a *duration* varies 3-5x between a laptop and a
CI runner, so this file is opt-in (`pytest -m performance`, or `make
benchmark`) and gated only against gross regression
(``--benchmark-compare-fail=mean:200%`` -- see the Makefile targets), never
on an absolute threshold.

Every benchmarked function here is pure CPU with no I/O -- no Ollama, no
Qdrant, no Postgres. Benchmarking a network call would measure this
container's network stack and the other service's own load, not this
repo's code; that is what ``perf/k6/`` (Workstream E2) is for.

``PrototypeMatcher.match`` is the one async function in this list --
``benchmark()`` only calls synchronous callables, so it is wrapped in
``asyncio.run(...)`` per call. That per-call event-loop setup cost is
included in the measured time; acceptable here since the comparison is
relative (this run vs. the committed baseline), not absolute, and every
future run pays the identical fixed overhead.
"""

import asyncio
import json

import pytest
from langchain_core.documents import Document

from app.ai.documents.anchors import build_page_map
from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.guardrails.pii import find_pii
from app.ai.retrieval.fusion import reciprocal_rank_fusion
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.semantic.prototype_matcher import PrototypeMatcher
from app.ai.verification.confidence_rules import RuleFinding, score_findings
from app.ai.verification.draft_verifier import verify_draft
from app.domains.chat.router import make_serializable

pytestmark = pytest.mark.performance

_PARAGRAPH = (
    "Sayın Makam, ilgi yazınızda belirtilen hususlar incelenmiş olup "
    "gereğinin yapılması için ilgili birimlere bilgi verilmiştir. "
)
_CORPUS_TEXT = (_PARAGRAPH * 300)[:50_000]

_DRAFT_TEXT = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazınızda belirtilen hususlar incelenmiştir. Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)
_SOURCE_DOCUMENT = "İlgi yazı: hususların incelenmesi talep edilmiştir. Sayı: E-1-1, Tarih: 30.07.2026."


def test_sparse_bm25_encode_document(benchmark):
    encoder = SparseBM25Encoder()
    benchmark(encoder.encode_document, _CORPUS_TEXT)


def test_sparse_bm25_encode_query(benchmark):
    encoder = SparseBM25Encoder()
    benchmark(encoder.encode_query, "ilgili birimlere bilgi verilmesi")


def test_reciprocal_rank_fusion(benchmark):
    dense = [Document(page_content=f"parça {i}: {_PARAGRAPH}") for i in range(20)]
    sparse = list(reversed(dense))
    benchmark(reciprocal_rank_fusion, [dense, sparse])


def test_build_page_map_and_page_for_offset(benchmark):
    pages = [_PARAGRAPH * 20 for _ in range(15)]

    def _run():
        page_map = build_page_map(pages)
        return [page_map.page_for_offset(offset) for offset in range(0, len(page_map.boundaries) * 500, 137)]

    benchmark(_run)


def test_recursive_chunker_split_text(benchmark):
    chunker = RecursiveChunker(chunk_size=1500, chunk_overlap=300)

    def _run():
        return asyncio.run(chunker.split_text(_CORPUS_TEXT))

    benchmark(_run)


def test_verify_draft(benchmark):
    benchmark(
        verify_draft,
        _DRAFT_TEXT,
        source_document=_SOURCE_DOCUMENT,
        context="",
        classification={"summary": "Hususların incelenmesi.", "fields": {}},
        instructions="",
    )


def test_confidence_rules_score_findings(benchmark):
    findings = [
        RuleFinding(rule_id="eksik_konu_satiri", detail="Konu satırı eksik"),
        RuleFinding(rule_id="dayanaksiz_iddia", detail="İlk iddia"),
        RuleFinding(rule_id="dayanaksiz_iddia", detail="İkinci iddia"),
    ]
    benchmark(score_findings, findings)


def test_guardrail_pii_scan(benchmark):
    text = (
        "Kimlik numarası 12345678901 olan başvuru sahibinin telefonu "
        "0532 123 45 67, IBAN'ı TR330006100519786457841326 olarak kayıtlıdır. "
    ) * 20
    benchmark(find_pii, text)


def test_make_serializable_on_a_large_graph_state(benchmark):
    state = {
        "plan_steps": ["classification", "brief", "draft", "routing"],
        "history": [{"role": "user" if i % 2 == 0 else "assistant", "content": _PARAGRAPH} for i in range(40)],
        "draft_result": {
            "status": "COMPLETED",
            "draft": _DRAFT_TEXT,
            "verification": {"score": 82.5, "applied_rules": []},
            "attempt_history": [{"attempt": i, "draft": _DRAFT_TEXT} for i in range(3)],
        },
        "classification_result": {"fields": {f"alan_{i}": f"değer {i}" for i in range(20)}},
    }
    benchmark(make_serializable, state)


def test_prototype_matcher_match_with_cached_vectors(benchmark, fake_embeddings, tmp_path):
    from app.ai.policy import POLICY_VERSION

    model = "test-embed:latest"
    payload = {
        "family": "intent",
        "model": model,
        "dimension": 3,
        "policy_version": POLICY_VERSION,
        "prototypes": [
            {"label": "draft", "text": "taslak", "vector": [1.0, 0.0, 0.0]},
            {"label": "analyze", "text": "analiz", "vector": [0.0, 1.0, 0.0]},
            {"label": "assist", "text": "soru", "vector": [0.0, 0.0, 1.0]},
        ],
    }
    (tmp_path / "intent.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    fake_embeddings.vectors["cevap metni kaleme al"] = [0.9, 0.1, 0.0]
    matcher = PrototypeMatcher(fake_embeddings, model_name=model, prototype_dir=tmp_path)

    def _run():
        return asyncio.run(matcher.match("cevap metni kaleme al", "intent"))

    benchmark(_run)
