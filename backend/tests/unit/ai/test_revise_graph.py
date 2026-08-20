"""Unit tests for the revise sub-graph's parity with draft_graph.verify_node
-- the gates the old single-call run_revise implementation never applied
(PII, fallback correspondence type) and the repair loop it never had."""

import asyncio

import pytest

from app.ai.session.focus import DraftVersion
from app.ai.workflows.revise_graph import _build_brief, create_revise_graph
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


def test_build_brief_surfaces_a_prior_rejection_reason():
    draft = _active_draft(status="REJECTED", rejection_reason="Üslup çok resmi değil.")

    brief = _build_brief(draft, context="")

    assert "Üslup çok resmi değil." in brief
    assert "Reddedilme Gerekçesi" in brief


def test_build_brief_omits_the_rejection_section_for_a_non_rejected_draft():
    draft = _active_draft(status="COMPLETED")

    brief = _build_brief(draft, context="")

    assert "Reddedilme Gerekçesi" not in brief


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
async def test_revise_never_emits_a_raw_token_the_graph_only_returns_the_draft(fake_llm):
    """Regression for the concatenation bug (old: one live, unvalidated
    "token" event per streamed chunk) and its own follow-up (old: a single
    post-validation token event from inside rewrite_node). Neither happens
    anymore -- rewrite_node buffers fully and returns the validated draft in
    its result; the client only ever sees it once, streamed from
    app.domains.chat.chat_service._enqueue_terminal_event after the whole
    turn (verify, any repair pass, guardrails) has settled. No node inside
    the revise graph ever reaches the SSE queue's "token" event at all."""
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Makam,\n\n",
        "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n",
        "Arz ederim.\n\nAli Veli\nGenel Müdür",
    ]
    graph = create_revise_graph(fake_llm)

    queue = asyncio.Queue()
    config = {"configurable": {"status_queue": queue}}

    final_state = await graph.ainvoke(
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
        if event.get("event") == "token":
            tokens.append(event["text"])

    assert tokens == []
    assert "Sayın Makam" in final_state["draft"]


@pytest.mark.asyncio
async def test_a_reviser_that_elides_previously_filled_content_is_flagged(fake_llm):
    """A whole-draft rewrite (no located target, see instruction.py's
    scope="whole" default) is never spliced through `_merge` -- the model's
    raw output becomes the draft outright. If it stands in an ellipsis for
    content it judged "unchanged" instead of reproducing it, nothing but
    this check would ever notice, and the previously-filled addressee/body
    the user already supplied would silently vanish."""
    fake_llm.stream_chunks = ["Konu: Yıllık İzin Talebi\n\n...\n\nArz ederim.\nAli Veli"]
    graph = create_revise_graph(fake_llm)

    active_draft = _active_draft(
        text=(
            "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\n"
            "Sayın Ahmet Yılmaz,\n\n"
            "İlgi yazı kapsamında 15-20 Ağustos 2026 tarihleri arasında yıllık izin "
            "kullanmak istediğimi arz ederim. Bu süre zarfında yerime vekalet edecek "
            "personel Mehmet Kaya'dır.\n\n"
            "Arz ederim.\n\nAli Veli\nGenel Müdür"
        )
    )

    result = await graph.ainvoke(
        {
            "active_draft": active_draft,
            "instructions": "Bunu daha iyi yap.",
            "reasoning_level": "fast",
        }
    )

    assert any(item["kind"] == "content_loss" for item in result["repair_items"])
    assert result["requires_human_approval"] is True
    assert "içerik" in result["evaluation_notes"].lower() or "kısaltma" in result["evaluation_notes"].lower()
    # The elided text still ships (repair is bounded and "fast" allows only
    # one attempt) -- but flagged for a human, never silently as COMPLETED.
    assert result["status"] == StepStatus.NEEDS_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_an_explicit_deletion_instruction_is_honoured_not_reverted(fake_llm):
    """The bug this closes: "vekalet eden personelle ilgili cümleleri sil"
    used to be silently ignored on the whole-draft path (no ordinal/section
    named, so no target span located, see instruction.py's scope="whole"
    default) two ways at once -- the rewrite prompt's own "never delete
    already-filled information" rule directly contradicted the user's own
    deletion request, and even a reviser that did comply had the resulting
    shrink misflagged as accidental content_loss and looped into a repair
    pass whose prompt says to restore dropped content, silently undoing the
    deletion. Neither happens anymore."""
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\n"
        "Sayın Ahmet Yılmaz,\n\n"
        "İlgi yazı kapsamında yıllık izin kullanmak istediğimi arz ederim.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]
    graph = create_revise_graph(fake_llm)

    active_draft = _active_draft(
        text=(
            "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\n"
            "Sayın Ahmet Yılmaz,\n\n"
            "İlgi yazı kapsamında 15-20 Ağustos 2026 tarihleri arasında yıllık izin "
            "kullanmak istediğimi arz ederim. Bu süre zarfında yerime vekalet edecek "
            "personel Mehmet Kaya'dır. Mehmet Kaya, kurumumuzda beş yıldır görev "
            "yapmakta olup gerekli yetkiye sahiptir ve iznim süresince tüm iş ve "
            "işlemlerimi eksiksiz şekilde yürütecektir.\n\n"
            "Arz ederim.\n\nAli Veli\nGenel Müdür"
        )
    )

    result = await graph.ainvoke(
        {
            "active_draft": active_draft,
            "instructions": "Vekalet eden personelle ilgili cümleleri sil.",
            "reasoning_level": "fast",
        }
    )

    messages = fake_llm.stream_calls[0]["messages"]
    prompt = "\n".join(message.get("content", "") for message in messages)
    assert "açıkça bir cümlenin/kısmın silinmesini" in prompt

    assert "Mehmet Kaya" not in result["draft"]
    assert not any(item["kind"] == "content_loss" for item in result["repair_items"])
    assert result["status"] == StepStatus.COMPLETED
    # Only ever the one rewrite pass -- no repair round undid the deletion.
    assert len(fake_llm.stream_calls) == 1


@pytest.mark.asyncio
async def test_audit_node_degrades_instead_of_failing_an_already_successful_revision(
    fake_llm, monkeypatch
):
    """C6 regression: audit_node's own docstring says a conflict finding
    here is advisory, never a gate -- so a failure to *produce* one must be
    advisory too. Before this fix, any exception raised while building the
    changelog/conflict report (a long instruction overflowing
    ChangeEntry.directive's own max_length was one concrete way this
    happened) propagated out of the graph and into run_revise's outer
    except Exception, which discards the whole revision and reports FAILED
    even though rewrite_node/verify_node already produced and verified a
    perfectly good draft two nodes earlier."""
    fake_llm.stream_chunks = [
        "Konu: Yıllık İzin Talebi\nSayı: E-1\nTarih: 30.07.2026\n\nSayın Vali Bey,\n\n"
        "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
        "Arz ederim.\n\nAli Veli\nGenel Müdür"
    ]

    def _boom(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr("app.ai.workflows.revise_graph.build_changelog", _boom)

    graph = create_revise_graph(fake_llm)
    result = await graph.ainvoke(
        {
            "active_draft": _active_draft(),
            "instructions": "Muhatabı değiştir.",
            "reasoning_level": "fast",
        }
    )

    assert result["status"] != StepStatus.FAILED
    assert "Sayın Vali Bey" in result["draft"]
    assert result["changelog"]["entries"] == []
    assert result["conflicts"] == []
