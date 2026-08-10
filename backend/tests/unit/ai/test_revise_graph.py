"""Unit tests for the revise sub-graph's parity with draft_graph.verify_node
-- the gates the old single-call run_revise implementation never applied
(PII, fallback correspondence type) and the repair loop it never had."""

import asyncio

import pytest

from app.ai.session.focus import DraftVersion
from app.ai.workflows.revise_graph import create_revise_graph
from app.core.enums.step_status import StepStatus

#: A real checksum-valid TCKN (see test_pii.py), not a live person's.
VALID_TCKN = "12345678950"


def _active_draft(**overrides) -> DraftVersion:
    defaults = dict(
        version=1,
        text="Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\nArz ederim.\n\nAli Veli\nGenel Müdür",
        correspondence_type="response_letter",
        confidence_score=90.0,
        created_from="draft",
        classification={"summary": "İzin talebi."},
        context="[MEVZUAT] İlgili Yönetmelik Madde 5: ...",
        source_document="Sayı: E-1, Tarih: 30.07.2026 tarihli evrak.",
        style_examples=(),
        correspondence_type_source="",
    )
    defaults.update(overrides)
    return DraftVersion(**defaults)


@pytest.mark.asyncio
async def test_pii_in_the_revised_draft_forces_human_approval(fake_llm):
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n"
        f"T.C. Kimlik No: {VALID_TCKN} olan personelin izin talebidir.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    assert result["pii_findings"]
    assert result["requires_human_approval"] is True
    assert result["status"] == StepStatus.NEEDS_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_a_grounded_pii_free_revision_does_not_require_approval(fake_llm):
    """Control for the PII test above -- without PII, the same shape of
    revision completes automatically."""
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n"
        "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    assert result["pii_findings"] == []
    assert result["requires_human_approval"] is False
    assert result["status"] == StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_a_fallback_correspondence_type_forces_human_approval(fake_llm):
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n"
        "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(correspondence_type_source="fallback"),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    assert result["requires_human_approval"] is True
    assert result["status"] == StepStatus.NEEDS_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_a_style_example_leak_is_reported_and_forces_approval(fake_llm):
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n"
        "Bursa Kaymakamlığı'na bilgi verilmiştir.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(
                style_examples=("Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır.",)
            ),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    leaks = result["verification"]["example_leaks"]
    assert leaks and leaks[0]["value"] == "Bursa Kaymakamlığı"
    assert result["requires_human_approval"] is True


@pytest.mark.asyncio
async def test_persistent_structural_defects_trigger_exactly_max_attempts_rewrites(
    fake_llm, monkeypatch
):
    from app.core.config import settings

    # Force the judge (and the conflict auditor, gated on the same switch)
    # off so "balanced"'s higher attempt cap can be tested without needing
    # FakeLLMClient to also satisfy a structured judge/auditor response.
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)

    # No "Konu:" line -> missing_structure never clears, so requires_revision
    # stays True on every attempt regardless of what the (fixed) fake stream
    # returns.
    fake_llm.stream_chunks = ["Sayın Makam,\n\nArz ederim.\n\nAli Veli\nGenel Müdür"]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "balanced",
        }
    )

    # "balanced" -> max_draft_attempts == 2 (see reasoning_levels.py).
    assert len(fake_llm.stream_calls) == 2
    assert result["status"] != StepStatus.FAILED


@pytest.mark.asyncio
async def test_a_scaffold_echoing_completion_fails_the_revision_instead_of_leaking(fake_llm):
    """The regression: a completion that echoes the reviser's own numbered
    brief scaffold (rather than plain draft prose) must never reach the
    user. rewrite_node buffers the whole completion and validates it before
    anything is shown -- this is the failure path that guarantees the leak
    never surfaces, not just becomes less likely."""
    fake_llm.stream_chunks = [
        "### BRIEF BELGESİ:\n1. Önceki Taslak Sürümü: 1\n2. Doğrulanmış Sınıflandırma: İzin talebi."
    ]
    graph = create_revise_graph(fake_llm)

    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    assert result["status"] == StepStatus.FAILED
    # The original draft is preserved, not the leaked scaffold text.
    assert result["draft"] == _active_draft().text
    assert "BRIEF BELGESİ" not in result["draft"]


@pytest.mark.asyncio
async def test_revise_never_emits_a_per_chunk_token_only_one_validated_text(fake_llm):
    """Regression for the concatenation bug: the old implementation emitted
    one "token" event per streamed chunk, live and unvalidated. rewrite_node
    now buffers fully and emits exactly one token event carrying the final,
    validated text -- see app.ai.workflows.events.emit_token's call site in
    rewrite_node."""
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n",
        "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n",
        "Arz ederim.\n\nAli Veli\nGenel Müdür",
    ]
    graph = create_revise_graph(fake_llm)

    queue = asyncio.Queue()
    config = {"configurable": {"status_queue": queue}}

    await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        },
        config=config,
    )

    tokens = []
    while not queue.empty():
        event = queue.get_nowait()
        if event.get("event") == "token" and event.get("node") == "revise":
            tokens.append(event["text"])

    assert len(tokens) == 1
    assert "Sayın Makam" in tokens[0]
