"""Unit tests for the single deterministic rule table a draft's confidence
score is computed from.

Before this module, the score blended a deterministic penalty with a
judge's own free-floating 0-100 opinion, which made the same draft capable
of scoring differently across two runs and let a judge timeout silently
change the arithmetic. These tests prove score_findings is a pure function
(same findings in, same score out, always) and that every rule in the table
behaves exactly as documented.
"""

from app.ai.verification.confidence_rules import (
    RULES,
    ConfidenceOutcome,
    RuleFinding,
    combine_outcomes,
    score_findings,
)


def test_no_findings_scores_full_marks_and_never_forces_approval():
    outcome = score_findings([])

    assert outcome.score == 100.0
    assert outcome.forces_approval is False
    assert outcome.applied_rules == ()


def test_scoring_the_same_findings_repeatedly_always_returns_the_same_outcome():
    """The reproducibility guarantee this whole module exists for."""
    findings = [
        RuleFinding(rule_id="dayanaksiz_iddia", detail="sayı: E-1"),
        RuleFinding(rule_id="eksik_konu_satiri"),
    ]

    outcomes = [score_findings(findings) for _ in range(50)]

    assert len({outcome.score for outcome in outcomes}) == 1
    assert len({outcome.forces_approval for outcome in outcomes}) == 1


def test_every_structural_rule_deducts_its_own_penalty_and_forces_approval():
    for rule_id in (
        "eksik_konu_satiri", "eksik_sayi_satiri", "eksik_tarih",
        "eksik_kapanis", "eksik_imza_blogu",
    ):
        outcome = score_findings([RuleFinding(rule_id=rule_id)])
        assert outcome.score == round(100.0 - RULES[rule_id].penalty, 1), rule_id
        assert outcome.forces_approval is True, rule_id


def test_dayanaksiz_iddia_is_per_occurrence_and_capped():
    rule = RULES["dayanaksiz_iddia"]
    # Below the cap: 3 occurrences.
    below_cap = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia") for _ in range(3)]
    )
    assert below_cap.score == round(100.0 - rule.penalty * 3, 1)

    # Well above the cap: many occurrences must not exceed it.
    many = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia") for _ in range(20)]
    )
    assert many.score == round(100.0 - rule.cap, 1)


def test_dayanaksiz_iddia_forces_approval_only_when_the_occurrence_says_so():
    """The one rule whose approval-forcing is conditional (strict=False) --
    see RuleFinding.forces_approval's own docstring."""
    lenient = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia", forces_approval=False)]
    )
    assert lenient.forces_approval is False
    assert lenient.score < 100.0  # still costs score either way

    strict = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia", forces_approval=True)]
    )
    assert strict.forces_approval is True


def test_ornek_sizintisi_and_doldurulmamis_yer_tutucu_are_per_occurrence_and_capped():
    for rule_id in ("ornek_sizintisi", "doldurulmamis_yer_tutucu"):
        rule = RULES[rule_id]
        outcome = score_findings(
            [RuleFinding(rule_id=rule_id) for _ in range(50)]
        )
        assert outcome.score == round(100.0 - rule.cap, 1), rule_id
        assert outcome.forces_approval is True, rule_id


def test_gelen_sayi_sizintisi_is_a_single_flat_penalty_forcing_approval():
    outcome = score_findings([RuleFinding(rule_id="gelen_sayi_sizintisi")])

    assert outcome.score == round(100.0 - RULES["gelen_sayi_sizintisi"].penalty, 1)
    assert outcome.forces_approval is True


def test_the_two_judge_rules_carry_zero_penalty_but_still_force_approval():
    """The core of what A4 changed: a critical judge finding gates the
    draft without moving the number at all."""
    for rule_id in ("yargic_kritik_bulgu", "talebi_karsilamiyor"):
        outcome = score_findings([RuleFinding(rule_id=rule_id)])
        assert outcome.score == 100.0, rule_id
        assert outcome.forces_approval is True, rule_id


def test_applied_rules_aggregates_occurrences_of_the_same_rule_into_one_row():
    outcome = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia", detail=f"claim {i}") for i in range(3)]
    )

    assert len(outcome.applied_rules) == 1
    applied = outcome.applied_rules[0]
    assert applied.rule_id == "dayanaksiz_iddia"
    assert applied.occurrences == 3
    assert applied.penalty_applied == RULES["dayanaksiz_iddia"].penalty * 3


def test_applied_rules_has_one_row_per_distinct_rule_sorted_by_id():
    outcome = score_findings(
        [RuleFinding(rule_id="eksik_tarih"), RuleFinding(rule_id="eksik_konu_satiri")]
    )

    ids = [rule.rule_id for rule in outcome.applied_rules]
    assert ids == sorted(ids)
    assert set(ids) == {"eksik_tarih", "eksik_konu_satiri"}


def test_multiple_different_rules_deduct_additively():
    outcome = score_findings(
        [RuleFinding(rule_id="eksik_konu_satiri"), RuleFinding(rule_id="eksik_tarih")]
    )

    expected = 100.0 - RULES["eksik_konu_satiri"].penalty - RULES["eksik_tarih"].penalty
    assert outcome.score == round(expected, 1)


def test_score_never_goes_below_zero():
    outcome = score_findings(
        [RuleFinding(rule_id="dayanaksiz_iddia") for _ in range(3)]
        + [RuleFinding(rule_id="ornek_sizintisi") for _ in range(3)]
        + [RuleFinding(rule_id="gelen_sayi_sizintisi")]
        + [RuleFinding(rule_id="eksik_konu_satiri"), RuleFinding(rule_id="eksik_sayi_satiri")]
        + [RuleFinding(rule_id="eksik_tarih"), RuleFinding(rule_id="eksik_kapanis")]
        + [RuleFinding(rule_id="eksik_imza_blogu")]
    )

    assert outcome.score == 0.0
    assert outcome.forces_approval is True


def test_combine_outcomes_sums_penalties_not_scores():
    a = score_findings([RuleFinding(rule_id="eksik_konu_satiri")])  # -8
    b = score_findings([RuleFinding(rule_id="eksik_tarih")])  # -4

    combined = combine_outcomes(a, b)

    assert combined.score == round(100.0 - 8.0 - 4.0, 1)
    assert combined.forces_approval is True
    assert {rule.rule_id for rule in combined.applied_rules} == {
        "eksik_konu_satiri", "eksik_tarih",
    }


def test_combine_outcomes_of_a_single_outcome_is_a_no_op():
    outcome = score_findings([RuleFinding(rule_id="mevzuat_baglami_yok")])

    assert combine_outcomes(outcome) == outcome


def test_combine_outcomes_with_nothing_reproduces_a_clean_scoring_pass():
    assert combine_outcomes() == score_findings([])


def test_every_rule_id_referenced_by_this_test_module_exists_in_the_table():
    """Guards against a typo'd rule_id silently scoring as if the rule did
    not exist (score_findings would KeyError on an unknown id at lookup
    time -- this just makes the intended universe explicit)."""
    expected = {
        "eksik_konu_satiri", "eksik_sayi_satiri", "eksik_tarih", "eksik_kapanis",
        "eksik_imza_blogu", "dayanaksiz_iddia", "ornek_sizintisi",
        "gelen_sayi_sizintisi", "doldurulmamis_yer_tutucu", "tur_tahmini",
        "mevzuat_baglami_yok", "pii_bulgusu", "icerik_kaybi",
        "yargic_kritik_bulgu", "talebi_karsilamiyor",
    }
    assert set(RULES.keys()) == expected
