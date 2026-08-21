"""The single, deterministic, auditable rule table a draft's confidence
score is computed from.

Before this module, the score was two things pretending to be one: a
deterministic penalty (unsupported claims + missing structure) blended
``0.6/0.4`` with a fast-tier LLM judge's own free-floating 0-100 opinion
(``app.ai.verification.llm_judge.merge_verdicts``, pre-refactor). Three
problems followed from that:

1. **Not reproducible.** The same draft, scored twice, could come back with
   two different numbers -- the judge leg is a model call, and even at
   ``temperature=0.0`` a local model is not guaranteed bit-identical output
   twice.
2. **Discontinuous.** When the judge call degraded (timeout, echo,
   disabled), the score silently *jumped* to the deterministic leg alone --
   the 0.4 weight simply vanished from the arithmetic rather than being
   redistributed or accounted for.
3. **Some real defects moved the gate but not the number.** A style-example
   leak or an unresolved placeholder forced human approval but left the
   *score* untouched (100.0), so two drafts needing review for very
   different reasons -- one perfect but for a single leaked institution
   name, one riddled with unfilled placeholders -- displayed the identical
   confidence number.

This module fixes all three by making the score a pure function of a list of
named rule findings: same findings in, same score out, always. The judge
still has a job -- flagging defects a regex cannot see (register, closing
direction, request fit) -- but it does that job by contributing findings
(gated through ``forces_approval``, at zero score weight) rather than a
number that gets averaged in. See ``app.ai.verification.llm_judge.
merge_verdicts`` for where a judge verdict is translated into findings.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

RuleCategory = Literal["yapi", "dayanak", "gizlilik", "belirsizlik", "butunluk"]


@dataclass(frozen=True)
class ConfidenceRule:
    """One named, penalized defect category.

    Attributes:
        id: Stable identifier. Reported on every ``AppliedRule`` so a score
            is traceable back to exactly which rules produced it -- this is
            what makes the score auditable rather than a black box.
        label: Turkish label shown to the user (e.g. in a "why is this
            62?" breakdown).
        category: Broad grouping for display -- structural, groundedness,
            confidentiality, unresolved-ness, or overall integrity.
        penalty: Points deducted. Per occurrence when ``per_occurrence`` is
            set, otherwise a single flat deduction regardless of how many
            findings fired this rule.
        per_occurrence: Whether ``penalty`` multiplies by how many findings
            fired this rule.
        cap: Ceiling on this rule's own total deduction, so a draft with
            many small issues of one kind still scores above one that is
            structurally broken outright -- the two failure modes must not
            collapse onto the same number. ``None`` means uncapped (only
            meaningful together with ``per_occurrence``; a non-per-occurrence
            rule's own single ``penalty`` is already its ceiling).
        forces_approval: Whether this rule, on its own, requires a human
            before the draft can be sent -- independent of the numeric
            score. A single finding can be true (the value copied is
            genuinely correct) and still be forbidden in this specific
            place (see ``gelen_sayi_sizintisi``), which is exactly why this
            is a separate flag rather than derived from the score.
    """

    id: str
    label: str
    category: RuleCategory
    penalty: float
    per_occurrence: bool = False
    cap: Optional[float] = None
    forces_approval: bool = True


#: The rule table. Calibrated to reproduce the pre-existing deterministic
#: weights exactly where one already existed (the five structural checks,
#: the unsupported-claim penalty/cap) -- and to give a real score weight,
#: for the first time, to defects that previously only flipped the approval
#: gate without moving the number at all (``ornek_sizintisi``,
#: ``doldurulmamis_yer_tutucu``, and everything ``merge_verdicts`` folds in
#: from outside the deterministic verifier: ``pii_bulgusu``,
#: ``tur_tahmini``, ``mevzuat_baglami_yok``, ``icerik_kaybi``). The two
#: judge-sourced rules carry zero penalty by design -- see this module's
#: docstring on why the judge no longer moves the score, only the gate.
RULES: dict[str, ConfidenceRule] = {
    rule.id: rule
    for rule in (
        ConfidenceRule("eksik_konu_satiri", "Eksik Konu satırı", "yapi", 8.0),
        ConfidenceRule("eksik_sayi_satiri", "Eksik Sayı satırı", "yapi", 6.0),
        ConfidenceRule("eksik_tarih", "Eksik Tarih bilgisi", "yapi", 4.0),
        ConfidenceRule("eksik_kapanis", "Eksik kapanış ifadesi", "yapi", 8.0),
        ConfidenceRule("eksik_imza_blogu", "Eksik imza bloğu", "yapi", 4.0),
        ConfidenceRule(
            "dayanaksiz_iddia", "Kaynakta doğrulanamayan iddia", "dayanak",
            12.0, per_occurrence=True, cap=60.0,
        ),
        ConfidenceRule(
            "ornek_sizintisi", "Üslup referans örneğinden sızıntı", "dayanak",
            20.0, per_occurrence=True, cap=40.0,
        ),
        ConfidenceRule(
            "gelen_sayi_sizintisi", "Gelen evrakın sayısı kendi Sayı alanına sızmış",
            "dayanak", 25.0,
        ),
        # Party-model rules (see app.ai.identity.parties and
        # draft_verifier._check_identity_slot_leaks): the counterparty's own
        # identity ending up in one of OUR identity slots. Two ids because
        # they are two different confusions, not the same one twice -- see
        # _check_identity_slot_leaks's own docstring for which is which.
        ConfidenceRule(
            "gonderen_muhatap_karisikligi", "Gönderen kurum muhatap/antet karışıklığı",
            "butunluk", 30.0,
        ),
        ConfidenceRule(
            "karsi_taraf_kimlik_sizintisi", "Karşı tarafın kimliği bizim kimlik alanımızda",
            "dayanak", 30.0,
        ),
        # Style/register rules (see app.ai.verification.style_checks) --
        # rule ids defined here alongside every other rule, detection
        # logic lives in its own module the same way structural/groundedness
        # detection lives in draft_verifier.py. The two pattern-heuristic
        # rules (kisi_tutarsizligi, dolgu_ifade) do not force approval on
        # their own: they still cost score and still feed the repair loop
        # (see llm_judge.merge_verdicts), but a heuristic match alone
        # shouldn't be able to strand an otherwise-clean draft in human
        # review the way a confirmed identity/groundedness defect does.
        # imza_blogu_uydurma keeps the table's default (forces_approval=True)
        # -- an exact bare-label match in the signature block is as
        # high-precision as gelen_sayi_sizintisi/karsi_taraf_kimlik_sizintisi.
        ConfidenceRule(
            "kisi_tutarsizligi", "Kişi/hitap tutarsızlığı", "butunluk",
            8.0, per_occurrence=True, cap=24.0, forces_approval=False,
        ),
        ConfidenceRule(
            "dolgu_ifade", "İçerik taşımayan dolgu ifadesi", "butunluk",
            4.0, per_occurrence=True, cap=16.0, forces_approval=False,
        ),
        ConfidenceRule(
            "meta_yorum", "Kendi analiz sürecine dair üst-yorum", "butunluk",
            4.0, per_occurrence=True, cap=16.0, forces_approval=False,
        ),
        ConfidenceRule("imza_blogu_uydurma", "İmza bloğunda uydurma/meta değer", "yapi", 10.0),
        ConfidenceRule(
            "doldurulmamis_yer_tutucu", "Doldurulmamış yer tutucu", "belirsizlik",
            5.0, per_occurrence=True, cap=30.0,
        ),
        ConfidenceRule("tur_tahmini", "Yazışma türü tahmin edildi", "belirsizlik", 10.0),
        ConfidenceRule("mevzuat_baglami_yok", "Doğrulanmış mevzuat bağlamı yok", "dayanak", 8.0),
        ConfidenceRule(
            "pii_bulgusu", "Kişisel veri bulgusu", "gizlilik",
            15.0, per_occurrence=True, cap=30.0,
        ),
        ConfidenceRule("icerik_kaybi", "İçerik kaybı (revizyonda elenmiş metin)", "butunluk", 25.0),
        # Zero-penalty by design -- see module docstring.
        ConfidenceRule("yargic_kritik_bulgu", "Kalite yargıcı: kritik bulgu", "butunluk", 0.0),
        ConfidenceRule("talebi_karsilamiyor", "Kalite yargıcı: talebi karşılamıyor", "butunluk", 0.0),
        # Same zero-penalty-by-design reasoning: a company rule violation
        # (app.ai.adapters.company_rules) gates approval and drives the
        # repair loop through its own JudgeFinding(kind="kurum_kurali")
        # entries (see llm_judge.REVISABLE_JUDGE_KINDS); this rule exists
        # only so the violation also lands in the auditable applied_rules
        # breakdown, even on the rare turn the judge reports
        # violated_rule_ids without a matching structured finding.
        ConfidenceRule("sirket_kurali_ihlali", "Şirket kuralı ihlali", "butunluk", 0.0),
    )
}


@dataclass(frozen=True)
class RuleFinding:
    """One occurrence of a rule firing, on a specific piece of evidence.

    Attributes:
        rule_id: Must be a key in ``RULES``.
        detail: Short, specific description of this occurrence (e.g. the
            exact unsupported value), for display alongside the score.
        forces_approval: Overrides the rule's own default for this specific
            occurrence when set. Exists for exactly one case today: an
            unsupported claim under a lenient (``strict=False``)
            correspondence type still costs score, but does not, on its
            own, force a human into the loop the way it does under a strict
            type (see ``app.ai.verification.draft_verifier.verify_draft``'s
            own ``strict`` parameter).
    """

    rule_id: str
    detail: str = ""
    forces_approval: Optional[bool] = None


class AppliedRule(BaseModel):
    """One rule's aggregated contribution to a final score.

    What a caller shows the user for "why is this score 62?" -- one row per
    rule that fired at least once, not one row per individual finding. A
    pydantic model (unlike the rest of this module) because it is the one
    piece of this module that crosses into ``VerificationReport`` and gets
    persisted/serialized (``draft_result["verification"]["applied_rules"]``).
    """

    rule_id: str
    label: str
    category: RuleCategory
    occurrences: int = Field(ge=1)
    penalty_applied: float = Field(ge=0.0)
    forces_approval: bool


@dataclass(frozen=True)
class ConfidenceOutcome:
    """The result of scoring a list of findings against ``RULES``.

    ``total_penalty`` (not just ``score``) is carried explicitly so
    ``combine_outcomes`` can sum two outcomes correctly -- ``100 - a`` and
    ``100 - b`` do not combine into ``100 - (a + b)`` by adding the scores
    themselves, only by adding the penalties first.
    """

    total_penalty: float
    forces_approval: bool
    applied_rules: tuple[AppliedRule, ...]

    @property
    def score(self) -> float:
        return max(0.0, round(100.0 - self.total_penalty, 1))


def score_findings(findings: list[RuleFinding]) -> ConfidenceOutcome:
    """Score a list of rule findings against ``RULES``.

    Pure and total: the same list of findings always produces the same
    outcome, regardless of what produced them or in what order they were
    collected -- this is the property the rest of the module docstring's
    "not reproducible" complaint is about fixing.

    Args:
        findings: Every rule finding collected for one draft, from every
            source (deterministic groundedness/structure, PII, correspondence
            type resolution, mevzuat context, judge findings).

    Returns:
        The combined outcome.
    """
    by_rule: dict[str, list[RuleFinding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)

    applied: list[AppliedRule] = []
    total_penalty = 0.0
    forces_approval = False

    for rule_id, occurrences in by_rule.items():
        rule = RULES[rule_id]
        count = len(occurrences)
        raw_penalty = rule.penalty * count if rule.per_occurrence else rule.penalty
        penalty = min(raw_penalty, rule.cap) if rule.cap is not None else raw_penalty
        total_penalty += penalty

        rule_forces = any(
            (occurrence.forces_approval if occurrence.forces_approval is not None else rule.forces_approval)
            for occurrence in occurrences
        )
        if rule_forces:
            forces_approval = True

        applied.append(
            AppliedRule(
                rule_id=rule_id,
                label=rule.label,
                category=rule.category,
                occurrences=count,
                penalty_applied=round(penalty, 1),
                forces_approval=rule_forces,
            )
        )

    return ConfidenceOutcome(
        total_penalty=round(total_penalty, 1),
        forces_approval=forces_approval,
        applied_rules=tuple(sorted(applied, key=lambda rule: rule.rule_id)),
    )


def combine_outcomes(*outcomes: ConfidenceOutcome) -> ConfidenceOutcome:
    """Merge outcomes computed separately (e.g. the deterministic verifier's
    own pass and the additional findings ``merge_verdicts`` folds in from
    PII/correspondence-type/mevzuat/judge) into one.

    Args:
        outcomes: Any number of previously computed outcomes. No rule id
            overlaps between the deterministic verifier's own rules and the
            ones ``merge_verdicts`` adds, so a plain sum is exact -- this
            does not need to re-bucket by rule id the way ``score_findings``
            does over raw findings.

    Returns:
        The combined outcome.
    """
    return ConfidenceOutcome(
        total_penalty=round(sum(outcome.total_penalty for outcome in outcomes), 1),
        forces_approval=any(outcome.forces_approval for outcome in outcomes),
        applied_rules=tuple(rule for outcome in outcomes for rule in outcome.applied_rules),
    )
