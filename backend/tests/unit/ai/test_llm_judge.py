"""Unit tests for the hybrid quality gate: judge_draft() and merge_verdicts()."""

import asyncio

import pytest

from app.ai.agents.judge import JudgeAgent
from app.ai.guardrails.pii import PiiFinding
from app.ai.revision.elision import ContentLossFinding
from app.ai.verification.confidence_rules import RuleFinding
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
    combined = merge_verdicts(
        _report(confidence_score=100.0), None, has_context=False, cites_legislation=True
    )

    assert combined.combined_score == 92.0  # 100 - 8 (mevzuat_baglami_yok)
    assert combined.requires_human_approval is True


def test_a_degraded_judge_call_forces_approval_even_at_a_clean_deterministic_score():
    """B7 regression: before this, a judge call that timed out/errored
    (verdict=None) scored and approved *identically* to a clean pass --
    silently dropping the quality gate exactly when it mattered most.
    judge_attempted=True (the judge was supposed to run, unlike an
    intentionally-skipped FAST-mode turn) now forces human approval on its
    own when the call degraded."""
    combined = merge_verdicts(_report(confidence_score=100.0), None, judge_attempted=True)

    assert combined.combined_score == 100.0  # the degradation itself is zero-penalty by design
    assert combined.requires_human_approval is True


def test_an_intentionally_skipped_judge_does_not_force_approval():
    """Control for the test above -- FAST mode (or a deployment setting)
    intentionally not running the judge at all must not force approval on
    every single draft it produces."""
    combined = merge_verdicts(_report(confidence_score=100.0), None, judge_attempted=False)

    assert combined.requires_human_approval is False


def test_missing_mevzuat_context_is_not_penalized_when_the_draft_never_cites_legislation():
    """B5 regression: a draft that never tried to cite any legislation
    (most cover letters/information notices) has no missing-context
    problem merely because none was retrieved -- before this,
    mevzuat_baglami_yok fired unconditionally whenever has_context was
    False, regardless of whether the draft ever referenced legislation."""
    combined = merge_verdicts(
        _report(confidence_score=100.0), None, has_context=False, cites_legislation=False
    )

    assert combined.combined_score == 100.0
    assert not any(rule.rule_id == "mevzuat_baglami_yok" for rule in combined.applied_rules)


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
        has_context=False, cites_legislation=True,  # -8
        pii_findings=[
            PiiFinding(kind="tckn", preview="1***"),
            PiiFinding(kind="iban", preview="TR***"),
        ],  # -15 * 2 = -30
    )

    assert combined.combined_score == 52.0  # 100 - 10 - 8 - 30
    assert combined.requires_human_approval is True
    assert combined.combined_score < MIN_AUTOMATED_CONFIDENCE_SCORE


def test_a_style_finding_deducts_score_and_becomes_a_repair_item():
    """Faz 4: app.ai.verification.style_checks findings are folded into the
    same additional-findings pass as PII/mevzuat/content-loss, and into
    repair_items the same way a judge finding is."""
    combined = merge_verdicts(
        _report(confidence_score=100.0),
        None,
        style_findings=[RuleFinding(rule_id="dolgu_ifade", detail="Tekrarlanan cümle (2x): 'X'")],
    )

    assert combined.combined_score == 96.0  # 100 - 4 (dolgu_ifade, single occurrence)
    assert any(item.kind == "dolgu_ifade" for item in combined.repair_items)
    repair_item = next(item for item in combined.repair_items if item.kind == "dolgu_ifade")
    assert repair_item.detail == "Tekrarlanan cümle (2x): 'X'"
    assert repair_item.suggested_fix


def test_a_heuristic_style_finding_does_not_force_approval_on_its_own():
    """kisi_tutarsizligi/dolgu_ifade are pattern heuristics -- they cost
    score and drive the repair loop, but (unlike gonderen_muhatap_karisikligi
    or karsi_taraf_kimlik_sizintisi) a single occurrence must not strand an
    otherwise-clean draft in human review on its own."""
    combined = merge_verdicts(
        _report(confidence_score=100.0),
        None,
        style_findings=[RuleFinding(rule_id="kisi_tutarsizligi", detail="'Ahmet'")],
    )

    assert combined.requires_human_approval is False


def test_an_imza_blogu_uydurma_style_finding_forces_approval():
    """Unlike the two register heuristics, a bare meta-value in the
    signature block is as high-precision as an exact identity leak, so it
    keeps the rule table's default forces_approval=True."""
    combined = merge_verdicts(
        _report(confidence_score=100.0),
        None,
        style_findings=[RuleFinding(rule_id="imza_blogu_uydurma", detail="'Ad Soyad'")],
    )

    assert combined.requires_human_approval is True


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
