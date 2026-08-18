"""Unit tests for the hybrid quality gate: judge_draft() and merge_verdicts()."""

import asyncio

import pytest

from app.ai.agents.judge import JudgeAgent
from app.ai.guardrails.pii import PiiFinding
from app.ai.revision.elision import ContentLossFinding
from app.ai.verification.draft_verifier import MIN_AUTOMATED_CONFIDENCE_SCORE, VerificationReport
from app.ai.verification.llm_judge import (
    DraftJudgeVerdict,
    JudgeFinding,
    judge_draft,
    merge_verdicts,
)
from app.ai.verification.missing_info import InfoQuestion


def _verdict(**overrides) -> DraftJudgeVerdict:
    fields = dict(
        addresses_request=True,
        register_ok=True,
        closing_direction="arz",
        closing_correct=True,
        muhatap_consistent=True,
        score=90.0,
        findings=[],
        rationale="Taslak talebi karşılıyor ve resmî üsluba uygun.",
    )
    fields.update(overrides)
    return DraftJudgeVerdict(**fields)


def _report(**overrides) -> VerificationReport:
    fields = dict(
        confidence_score=90.0,
        requires_human_approval=False,
        unsupported_claims=[],
        missing_structure=[],
        placeholder_count=0,
        evaluation_notes="ok",
    )
    fields.update(overrides)
    return VerificationReport(**fields)


# ==========================================
# judge_draft()
# ==========================================
@pytest.mark.asyncio
async def test_judge_draft_returns_the_verdict_on_success(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)
    verdict = _verdict()

    async def fake_run_structured(**kwargs):
        return verdict

    agent.run_structured = fake_run_structured

    result = await judge_draft(
        agent, draft="Sayın Makam, arz ederim.", brief="brief", correspondence_type="cover_letter",
        instructions="",
    )

    assert result is verdict


@pytest.mark.asyncio
async def test_judge_draft_includes_the_company_rules_block_in_the_prompt(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)
    captured_prompts: list[str] = []

    async def fake_run_structured(**kwargs):
        captured_prompts.append(kwargs["messages"])
        return _verdict()

    agent.run_structured = fake_run_structured

    await judge_draft(
        agent, draft="Sayın Makam, arz ederim.", brief="brief", correspondence_type="cover_letter",
        instructions="", company_rules_block="[K1] Kapanışta 'Arz ederim' kullan.",
    )

    assert "[K1] Kapanışta 'Arz ederim' kullan." in captured_prompts[0]


@pytest.mark.asyncio
async def test_judge_draft_degrades_to_none_on_timeout(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)

    async def hangs(**kwargs):
        await asyncio.sleep(10)

    agent.run_structured = hangs

    result = await judge_draft(
        agent, draft="x", brief="b", correspondence_type="cover_letter", instructions="",
        timeout_s=0.01,
    )

    assert result is None


@pytest.mark.asyncio
async def test_judge_draft_degrades_to_none_on_provider_exception(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)

    async def raises(**kwargs):
        raise RuntimeError("provider unavailable")

    agent.run_structured = raises

    result = await judge_draft(
        agent, draft="x", brief="b", correspondence_type="cover_letter", instructions=""
    )

    assert result is None


@pytest.mark.asyncio
async def test_judge_draft_rejects_a_verdict_that_echoes_the_draft(fake_fast_llm):
    agent = JudgeAgent(fake_fast_llm)
    draft = (
        "Sayın Genel Müdürlük makamına arz ederim ki bu evrak çok önemli bir "
        "konuyu ele almaktadır ve gerekli işlemlerin yapılmasını rica ederim"
    )
    # Rationale built almost entirely out of the draft's own tokens.
    echoing_verdict = _verdict(rationale=draft)

    async def fake_run_structured(**kwargs):
        return echoing_verdict

    agent.run_structured = fake_run_structured

    result = await judge_draft(
        agent, draft=draft, brief="b", correspondence_type="cover_letter", instructions=""
    )

    assert result is None


# ==========================================
# merge_verdicts()
# ==========================================
def test_the_judges_own_numeric_score_never_moves_the_combined_score():
    """The judge no longer contributes a blended number (see this module's
    own docstring) -- a judge verdict with no findings and
    addresses_request=True changes nothing about the score, however low its
    own `.score` field is, because that field is never read here."""
    combined = merge_verdicts(_report(confidence_score=80.0), _verdict(score=1.0))

    assert combined.combined_score == 80.0
    assert combined.judge_available is True


def test_merge_falls_back_to_deterministic_score_when_judge_unavailable():
    combined = merge_verdicts(_report(confidence_score=85.0), None)

    assert combined.combined_score == 85.0
    assert combined.judge_available is False
    assert "kullanılamadı" in combined.notes


def test_critical_finding_forces_human_approval_without_moving_the_score():
    """A critical judge finding gates approval through the rule table's own
    zero-penalty `yargic_kritik_bulgu` row (see confidence_rules.py's
    docstring) -- it no longer drags the score down artificially. A single
    critical defect being averaged away by an otherwise clean structural
    score was never the problem this was solving; the *number* now stays
    honest about what the deterministic checks actually found, while the
    *gate* still opens."""
    verdict = _verdict(
        score=95.0,
        findings=[
            JudgeFinding(
                kind="kapanis", severity="critical", detail="Yanlış kapanış yönü.",
                suggested_fix="Rica ederim yerine arz ederim kullan.",
            )
        ],
    )
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.combined_score == 95.0
    assert combined.requires_human_approval is True
    assert combined.requires_revision is True
    assert any(item.kind == "judge:kapanis" for item in combined.repair_items)
    assert any(
        rule.rule_id == "yargic_kritik_bulgu" and rule.penalty_applied == 0.0
        for rule in combined.applied_rules
    )


def test_critical_finding_of_a_non_revisable_kind_still_forces_approval_but_no_repair_item():
    """'mevzuat' and 'tutarlilik' findings can't be fixed by a text-only
    revision pass -- they should still gate approval, but not produce a
    repair instruction the reviser can't actually act on."""
    verdict = _verdict(
        score=95.0,
        findings=[
            JudgeFinding(
                kind="mevzuat", severity="critical", detail="Yanlış atıf.",
                suggested_fix="Farklı madde kullan.",
            )
        ],
    )
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.requires_human_approval is True
    assert not any(item.source == "judge" for item in combined.repair_items)


def test_addresses_request_false_forces_approval_regardless_of_score():
    verdict = _verdict(score=95.0, addresses_request=False)
    combined = merge_verdicts(_report(confidence_score=95.0), verdict)

    assert combined.requires_human_approval is True
    assert any(item.kind == "judge:talep" for item in combined.repair_items)


def test_deterministic_defects_become_revisable_repair_items():
    report = _report(
        confidence_score=50.0,
        missing_structure=["Konu satırı"],
        requires_human_approval=True,
    )
    combined = merge_verdicts(report, None)

    assert combined.requires_revision is True
    assert any(item.kind == "missing_structure" for item in combined.repair_items)


def test_missing_information_passes_through_unchanged():
    questions = [InfoQuestion(key="muhatap", label="[MUHATAP]")]
    combined = merge_verdicts(_report(), _verdict(), missing_information=questions)

    assert combined.missing_information == questions


# ===========================================================================
# merge_verdicts() -- signals folded in from outside the deterministic
# verifier (PII, a guessed correspondence type, missing mevzuat context,
# revision content loss). Each is its own confidence_rules.py row, so each
# has its own real score deduction now (previously only a bolt-on approval
# flag with no effect on the number at all).
# ===========================================================================
def test_a_pii_finding_deducts_score_and_forces_approval():
    combined = merge_verdicts(
        _report(confidence_score=100.0), None,
        pii_findings=[PiiFinding(kind="tckn", preview="12345678***")],
    )

    assert combined.combined_score == 85.0  # 100 - 15 (pii_bulgusu)
    assert combined.requires_human_approval is True


def test_a_guessed_correspondence_type_deducts_score_and_forces_approval():
    combined = merge_verdicts(
        _report(confidence_score=100.0), None, correspondence_type_fallback=True
    )

    assert combined.combined_score == 90.0  # 100 - 10 (tur_tahmini)
    assert combined.requires_human_approval is True


def test_missing_mevzuat_context_deducts_score_and_forces_approval():
    combined = merge_verdicts(_report(confidence_score=100.0), None, has_context=False)

    assert combined.combined_score == 92.0  # 100 - 8 (mevzuat_baglami_yok)
    assert combined.requires_human_approval is True


def test_content_loss_deducts_score_forces_approval_and_becomes_a_repair_item():
    loss = ContentLossFinding(
        detail="Taslakta önceki içeriğin yerine kısaltma kullanılmış.",
        suggested_fix="Elenen paragrafı kelimesi kelimesine geri getir.",
    )
    combined = merge_verdicts(_report(confidence_score=100.0), None, content_loss=loss)

    assert combined.combined_score == 75.0  # 100 - 25 (icerik_kaybi)
    assert combined.requires_human_approval is True
    assert any(item.kind == "content_loss" for item in combined.repair_items)


def test_multiple_additional_findings_deduct_cumulatively():
    combined = merge_verdicts(
        _report(confidence_score=100.0), None,
        correspondence_type_fallback=True,  # -10
        has_context=False,  # -8
        pii_findings=[
            PiiFinding(kind="tckn", preview="1***"),
            PiiFinding(kind="iban", preview="TR***"),
        ],  # -15 * 2 = -30
    )

    assert combined.combined_score == 52.0  # 100 - 10 - 8 - 30
    assert combined.requires_human_approval is True
    assert combined.combined_score < MIN_AUTOMATED_CONFIDENCE_SCORE


def test_no_additional_signals_leaves_the_deterministic_score_untouched():
    combined = merge_verdicts(_report(confidence_score=100.0), None)

    assert combined.combined_score == 100.0
    assert combined.requires_human_approval is False


def test_applied_rules_combines_the_reports_own_rules_with_the_additional_ones():
    report = VerificationReport(
        confidence_score=92.0,
        requires_human_approval=False,
        missing_structure=["Sayı satırı"],
        applied_rules=[
            {
                "rule_id": "eksik_sayi_satiri", "label": "Eksik Sayı satırı",
                "category": "yapi", "occurrences": 1, "penalty_applied": 8.0,
                "forces_approval": True,
            }
        ],
    )
    combined = merge_verdicts(report, None, correspondence_type_fallback=True)

    rule_ids = {rule.rule_id for rule in combined.applied_rules}
    assert rule_ids == {"eksik_sayi_satiri", "tur_tahmini"}


def test_clean_draft_and_verdict_requires_neither_revision_nor_approval():
    combined = merge_verdicts(_report(), _verdict())

    assert combined.requires_revision is False
    assert combined.requires_human_approval is False


# ==========================================
# Company rules (#214)
# ==========================================
def test_company_rule_violation_becomes_a_revisable_repair_item():
    """A 'kurum_kurali' judge finding is exactly the kind of targeted,
    textual defect the existing verify -> revise repair loop already
    handles -- no separate mechanism needed, see llm_judge.py's own
    REVISABLE_JUDGE_KINDS docstring."""
    verdict = _verdict(
        score=90.0,
        company_rules_ok=False,
        violated_rule_ids=["K2"],
        findings=[
            JudgeFinding(
                kind="kurum_kurali", severity="major",
                detail="Kapanış 'Rica ederim' yerine 'Arz ederim' olmalıydı (K2).",
                suggested_fix="Kapanışı 'Arz ederim' yap.",
            )
        ],
    )
    combined = merge_verdicts(_report(confidence_score=90.0), verdict)

    assert combined.requires_revision is True
    assert any(item.kind == "judge:kurum_kurali" for item in combined.repair_items)
    assert any(rule.rule_id == "sirket_kurali_ihlali" for rule in combined.applied_rules)
    assert all(
        rule.rule_id != "sirket_kurali_ihlali" or rule.penalty_applied == 0.0
        for rule in combined.applied_rules
    )


def test_company_rules_ok_true_by_default_when_no_rules_were_supplied():
    """A judge asked to grade against no rules at all must not spuriously
    flag a violation -- judge.md's own criterion 5 skips itself in that
    case, and the verdict schema defaults company_rules_ok=True."""
    combined = merge_verdicts(_report(), _verdict())

    assert not any(rule.rule_id == "sirket_kurali_ihlali" for rule in combined.applied_rules)
