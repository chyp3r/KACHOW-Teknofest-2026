"""Hybrid quality gate: the deterministic verifier plus a fast-tier LLM judge.

``draft_verifier.verify_draft`` catches fabricated numbers, dates, institutions
and citations, and checks structural completeness -- all set-membership and
regex, all reproducible, all free. It cannot judge whether a draft answers the
actual request, uses the correct arz/rica direction for the addressee
hierarchy, reads as officially registered Turkish, or stays consistent about
who it is addressed to. Those require reasoning, not string matching, so this
module adds a single small structured call to the fast-tier model for them.

The judge is deliberately not allowed to re-emit the draft: every string field
on its verdict is length-capped, and a post-validation guard rejects a verdict
whose text strongly overlaps the draft it graded. A model that echoes the
draft back is not judging it, and asking it to try again just produces a
second echo -- so an echo is treated as a degraded judge call, not a retry.

``merge_verdicts`` used to blend the judge's own 0-100 ``score`` into the
final number (``0.6 * deterministic + 0.4 * judge``). That made the score
unreproducible (the same draft could score differently across two judge
calls) and discontinuous (a degraded judge call silently dropped the 0.4
weight instead of redistributing it). The judge no longer contributes a
number: its findings become ``RuleFinding``s in the same single table
``app.ai.verification.confidence_rules`` uses for everything else, at zero
score weight (see that module's docstring) -- the judge still gates approval
and still drives the repair loop, it just never moves the number.
"""

import asyncio
import logging
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.agents.judge import JudgeAgent
from app.ai.guardrails.pii import PiiFinding
from app.ai.policy import get_policy
from app.ai.revision.elision import ContentLossFinding
from app.ai.verification.confidence_rules import AppliedRule, RuleFinding, score_findings
from app.ai.verification.draft_verifier import (
    MIN_AUTOMATED_CONFIDENCE_SCORE,
    VerificationReport,
    _fold,
)
from app.ai.verification.missing_info import InfoQuestion
from app.ai.workflows.correspondence import format_correspondence_profile
from app.core.config import settings
from app.observability.ai_metrics import JUDGE_FAILURES

logger = logging.getLogger(__name__)

#: Judge findings whose fixes a text-only revision pass can actually make.
#: Findings of kind "mevzuat" (wrong legal citation match) or "tutarlilik"
#: (broad internal inconsistency) are reported and can force human approval,
#: but are deliberately excluded here -- a rewrite cannot fix a bad citation
#: match without a new retrieval, and "make it more consistent" is too vague
#: a revision instruction to hand a 9B model without risking overcorrection.
#: "kurum_kurali" (a company's own mandatory drafting rule, see
#: app.ai.adapters.company_rules) is included -- unlike mevzuat/tutarlilik,
#: a rule violation is exactly the kind of targeted, textual defect a repair
#: pass can fix (e.g. "kapanışı 'Arz ederim' yap"), the same shape as the
#: existing kapanis/uslup findings.
REVISABLE_JUDGE_KINDS = frozenset({"kapanis", "uslup", "talep", "muhatap", "kurum_kurali"})

#: Above this fraction of a judge verdict's own tokens appearing in the draft,
#: treat the verdict as an echo of the draft rather than a judgement of it.
_ECHO_OVERLAP_THRESHOLD = get_policy().verification.judge_echo_overlap_threshold


class JudgeFinding(BaseModel):
    """A single concrete defect the judge found, with a specific fix."""

    kind: Literal[
        "hitap", "kapanis", "talep", "uslup", "muhatap", "mevzuat", "tutarlilik", "kurum_kurali"
    ]
    severity: Literal["critical", "major", "minor"]
    detail: str = Field(max_length=200)
    suggested_fix: str = Field(max_length=200)


class DraftJudgeVerdict(BaseModel):
    """The judge's structured assessment. No field may carry draft text."""

    addresses_request: bool = Field(
        description="Taslak, gelen evrakın veya kullanıcının asıl talebini karşılıyor mu."
    )
    register_ok: bool = Field(description="Resmî üslup korunuyor mu.")
    closing_direction: Literal["arz", "rica", "arz_ve_rica", "bilgilendirme", "yok"] = Field(
        description="Taslakta fiilen kullanılan kapanışın yönü."
    )
    closing_correct: bool = Field(
        description="Kapanış yönü muhatap hiyerarşisiyle uyumlu mu."
    )
    muhatap_consistent: bool = Field(
        description="Başlık, gövde hitabı ve kapanış yönü birbiriyle tutarlı mı."
    )
    company_rules_ok: bool = Field(
        default=True,
        description=(
            "Taslak, verilen şirket kurallarının tamamına uyuyor mu. Kural "
            "verilmemişse true."
        ),
    )
    violated_rule_ids: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="İhlal edilen kuralların kimlikleri (örn. ['K2', 'K5']).",
    )
    score: float = Field(ge=0.0, le=100.0)
    findings: list[JudgeFinding] = Field(default_factory=list, max_length=5)
    rationale: str = Field(max_length=400)


class RepairItem(BaseModel):
    """One targeted instruction handed back to the reviser."""

    kind: str
    detail: str
    suggested_fix: str = ""
    source: Literal["deterministic", "judge"]


class CombinedVerdict(BaseModel):
    """The merged outcome the draft graph's router acts on."""

    combined_score: float
    requires_human_approval: bool
    requires_revision: bool
    repair_items: list[RepairItem] = Field(default_factory=list)
    missing_information: list[InfoQuestion] = Field(default_factory=list)
    judge_available: bool
    notes: str = ""
    applied_rules: list[AppliedRule] = Field(
        default_factory=list,
        description=(
            "report.applied_rules plus every additional rule finding this "
            "merge folded in (PII, yazışma türü tahmini, mevzuat bağlamı "
            "yokluğu, içerik kaybı, yargıç bulguları) -- the full, auditable "
            "breakdown behind combined_score."
        ),
    )


def _reject_draft_echo(verdict: DraftJudgeVerdict, draft: str) -> bool:
    """Detect a judge verdict that echoes the draft instead of judging it.

    Args:
        verdict: The candidate verdict.
        draft: The draft text it was supposed to assess.

    Returns:
        True when the verdict's text overlaps the draft too strongly to trust.
    """
    draft_tokens = set(_fold(draft).split())
    if not draft_tokens:
        return False

    fields = [verdict.rationale, *(f"{f.detail} {f.suggested_fix}" for f in verdict.findings)]
    text_tokens = [token for token in _fold(" ".join(fields)).split() if len(token) > 2]
    if len(text_tokens) < 8:
        return False

    overlap = sum(1 for token in text_tokens if token in draft_tokens) / len(text_tokens)
    return overlap > _ECHO_OVERLAP_THRESHOLD


async def judge_draft(
    agent: JudgeAgent,
    *,
    draft: str,
    brief: str,
    correspondence_type: str,
    instructions: str,
    timeout_s: float | None = None,
    sub_genre: str = "",
    company_rules_block: str = "",
) -> DraftJudgeVerdict | None:
    """Ask the fast-tier judge to assess a draft. Never raises.

    Args:
        agent: A constructed :class:`JudgeAgent` (fast-tier client).
        draft: The draft to assess.
        brief: The grounding brief handed to the writer.
        correspondence_type: The resolved :class:`CorrespondenceType` value.
        instructions: The user's drafting instructions.
        timeout_s: Hard timeout; defaults to ``settings.DRAFT_JUDGE_TIMEOUT_SECONDS``.
        sub_genre: Free-text genre label ("itiraz dilekçesi") when the draft
            targets a specific genre outside the four spec'd types -- see
            ``app.ai.workflows.correspondence.format_correspondence_profile``.
        company_rules_block: The requesting company's mandatory rules,
            already rendered (see
            ``app.ai.adapters.injection.format_rules_block``). Empty when
            no rules are configured -- ``judge.md``'s own criterion 5 skips
            itself in that case.

    Returns:
        The verdict, or ``None`` on timeout, a schema failure, a provider
        error, or a detected echo -- all of which degrade the quality gate to
        the deterministic score rather than blocking the draft flow.
    """
    timeout = timeout_s if timeout_s is not None else settings.DRAFT_JUDGE_TIMEOUT_SECONDS
    prompt = (
        "### BRIEF BELGESİ:\n"
        f"{brief}\n\n"
        "### YAZIŞMA TÜRÜ:\n"
        f"{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        "### KULLANICI TALİMATLARI:\n"
        f"{instructions or '(talimat verilmedi)'}\n\n"
        "### ŞİRKET KURALLARI:\n"
        f"{company_rules_block or '(kural verilmedi)'}\n\n"
        "### DEĞERLENDİRİLECEK TASLAK:\n"
        f"{draft}"
    )

    try:
        verdict: DraftJudgeVerdict = await asyncio.wait_for(
            agent.run_structured(
                messages=prompt,
                response_model=DraftJudgeVerdict,
                temperature=0.0,
                max_retries=1,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Draft judge timed out after %.0fs; degrading.", timeout)
        JUDGE_FAILURES.labels(reason="timeout").inc()
        return None
    except Exception:
        logger.exception("Draft judge call failed; degrading.")
        JUDGE_FAILURES.labels(reason="exception").inc()
        return None

    if _reject_draft_echo(verdict, draft):
        logger.warning("Draft judge verdict echoed the draft; treating as degraded.")
        JUDGE_FAILURES.labels(reason="echo").inc()
        return None

    return verdict


def merge_verdicts(
    report: VerificationReport,
    verdict: DraftJudgeVerdict | None,
    *,
    missing_information: list[InfoQuestion] | None = None,
    pii_findings: Optional[Sequence[PiiFinding]] = None,
    correspondence_type_fallback: bool = False,
    has_context: bool = True,
    content_loss: Optional[ContentLossFinding] = None,
) -> CombinedVerdict:
    """Combine every signal about a draft into one deterministic outcome.

    The score is additive, not blended: ``report``'s own deterministic
    penalty (recovered as ``100 - report.confidence_score``, since the
    report does not expose its raw penalty) plus one more rule-table pass
    (``app.ai.verification.confidence_rules``) over everything this
    function alone knows about -- PII, a guessed correspondence type, a
    missing mevzuat context, revision content loss, and the judge's own
    findings. The judge's numeric ``verdict.score`` is never read here (see
    this module's docstring) -- only ``verdict.findings`` and
    ``verdict.addresses_request`` feed the table, both at the rule table's
    own zero-penalty ``yargic_kritik_bulgu``/``talebi_karsilamiyor`` rows,
    so a critical judge finding gates approval without moving the number.

    Args:
        report: The deterministic verification report.
        verdict: The judge's verdict, or ``None`` if the judge call degraded.
        missing_information: Pre-built placeholder questions, when the draft
            has any. Kept as an explicit parameter rather than derived here so
            this function stays a pure merge over its inputs.
        pii_findings: Personal-data findings in the draft (see
            ``app.ai.guardrails.pii.find_pii``), if any.
        correspondence_type_fallback: Whether the correspondence type was
            guessed rather than resolved from an explicit signal (see
            ``app.ai.workflows.correspondence.resolve_correspondence_type``).
        has_context: Whether any verified legislation excerpt backs this
            draft. ``False`` means the system had nothing to ground it in.
        content_loss: A detected elision between this draft and the version
            it revised (see ``app.ai.revision.elision.detect_content_loss``),
            when this is a revision pass and one was found.

    Returns:
        The combined verdict the draft graph's router acts on.
    """
    judge_available = verdict is not None

    repair_items: list[RepairItem] = [
        RepairItem(
            kind="unsupported_claim",
            source="deterministic",
            detail=f"{claim.kind}: '{claim.value}' -- {claim.explanation}",
            suggested_fix="Kaynakta doğrulanamayan bu ifadeyi kaldır veya yer tutucuyla değiştir.",
        )
        for claim in report.unsupported_claims
    ]
    repair_items.extend(
        RepairItem(
            kind="missing_structure",
            source="deterministic",
            detail=f"Eksik yapısal unsur: {label}",
            suggested_fix=f"Brief'teki ilgili bilgiyi kullanarak '{label}' unsurunu ekle.",
        )
        for label in report.missing_structure
    )
    # Unlike example_leaks (never fed into repair -- a repair pass sees the
    # exact same style examples and could reproduce the same leak), this is
    # a plain deletion: replace the draft's own Sayı: value with the
    # placeholder it should have been. A repair pass has nothing to
    # reproduce the leak *from* here -- the incoming number simply should
    # not be in this line at all.
    repair_items.extend(
        RepairItem(
            kind="incoming_number_leak",
            source="deterministic",
            detail=(
                f"Taslağın kendi Sayı: satırı gelen evrakın sayısını taşıyor: "
                f"'{leak.value}'."
            ),
            suggested_fix=(
                "Kendi Sayı: satırını '[Belge Sayısı]' yer tutucusuyla değiştir; "
                "gelen evrakın sayısını yalnızca İlgi satırında bırak."
            ),
        )
        for leak in report.incoming_number_leaks
    )

    # Every finding this function alone is responsible for -- everything the
    # deterministic verifier already scored lives in `report.applied_rules`
    # instead, combined below rather than re-derived here.
    additional_findings: list[RuleFinding] = [
        RuleFinding(rule_id="pii_bulgusu", detail=finding.kind) for finding in (pii_findings or [])
    ]
    if correspondence_type_fallback:
        additional_findings.append(RuleFinding(rule_id="tur_tahmini"))
    if not has_context:
        additional_findings.append(RuleFinding(rule_id="mevzuat_baglami_yok"))
    if content_loss is not None:
        additional_findings.append(RuleFinding(rule_id="icerik_kaybi", detail=content_loss.detail))
        repair_items.append(
            RepairItem(
                kind="content_loss",
                source="deterministic",
                detail=content_loss.detail,
                suggested_fix=content_loss.suggested_fix,
            )
        )

    if judge_available:
        for finding in verdict.findings:
            if finding.severity == "critical":
                additional_findings.append(
                    RuleFinding(rule_id="yargic_kritik_bulgu", detail=finding.detail)
                )
            if finding.severity in {"critical", "major"} and finding.kind in REVISABLE_JUDGE_KINDS:
                repair_items.append(
                    RepairItem(
                        kind=f"judge:{finding.kind}",
                        source="judge",
                        detail=finding.detail,
                        suggested_fix=finding.suggested_fix,
                    )
                )
        if not verdict.company_rules_ok and verdict.violated_rule_ids:
            additional_findings.append(
                RuleFinding(
                    rule_id="sirket_kurali_ihlali",
                    detail=", ".join(verdict.violated_rule_ids),
                )
            )
        if not verdict.addresses_request:
            additional_findings.append(RuleFinding(rule_id="talebi_karsilamiyor"))
            repair_items.append(
                RepairItem(
                    kind="judge:talep",
                    source="judge",
                    detail="Taslak, gelen evrakın veya kullanıcının asıl talebini karşılamıyor.",
                    suggested_fix="Taslağı gelen evrakın/kullanıcının asıl talebine göre yeniden odakla.",
                )
            )

    additional_outcome = score_findings(additional_findings)
    # `report.confidence_score` is already `max(0, 100 - penalty)` -- this
    # recovers that penalty rather than re-deriving it from
    # `report.applied_rules`, which a hand-built report (a test, or any
    # future caller that skips `verify_draft`) may not have populated.
    deterministic_penalty = 100.0 - report.confidence_score
    combined_penalty = round(deterministic_penalty + additional_outcome.total_penalty, 1)
    combined_score = max(0.0, round(100.0 - combined_penalty, 1))

    requires_human_approval = (
        report.requires_human_approval
        or additional_outcome.forces_approval
        or combined_score < MIN_AUTOMATED_CONFIDENCE_SCORE
    )
    requires_revision = bool(repair_items)

    notes_parts = [report.evaluation_notes]
    if judge_available:
        notes_parts.append(f"Yargıç değerlendirmesi: {verdict.rationale}")
    else:
        notes_parts.append(
            "Kalite yargıcı kullanılamadı; yalnızca deterministik doğrulama sonucuna göre karar verildi."
        )
    notes = " ".join(part for part in notes_parts if part)

    return CombinedVerdict(
        combined_score=combined_score,
        requires_human_approval=requires_human_approval,
        requires_revision=requires_revision,
        repair_items=repair_items,
        missing_information=list(missing_information or []),
        judge_available=judge_available,
        notes=notes,
        applied_rules=[*report.applied_rules, *additional_outcome.applied_rules],
    )
