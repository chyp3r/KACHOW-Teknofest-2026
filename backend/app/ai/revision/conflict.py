"""Instruction-vs-mevzuat/source conflict auditing for a revision.

The user's revision instruction is applied *verbatim and unconditionally* --
see ``app.ai.workflows.revise_graph``'s ``rewrite`` node, which never
consults this module before generating. This module runs strictly
*afterward*, on the already-merged draft, and its only effect is to attach
warnings and (for major/critical findings) force a human approval gate. It
never blocks, reverts or softens an edit.

``ConflictReport.applied_anyway`` is a hard invariant of this module, not a
policy this module could ever be configured to flip: every finding this
module can produce describes a defect in a change that has already
happened, not a decision about whether it should happen.

Two layers, same shape as the deterministic verifier + LLM judge pairing in
``app.ai.verification``:

- ``detect_conflicts_deterministic`` -- free, reproducible, regex/set-based.
  Always runs.
- ``assess_conflicts_llm`` -- one fast-tier structured call for the
  contradictions a regex cannot see (a normative statement that
  contradicts a mevzuat clause in meaning, not just in citation). Gated by
  ``settings.REVISION_CONFLICT_AUDIT_ENABLED`` and the reasoning level's
  judge switch; degrades to ``[]`` on any failure, same as ``judge_draft``.
"""

import asyncio
import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.agents.conflict_auditor import ConflictAuditorAgent
from app.ai.guardrails.pii import find_pii
from app.ai.policy import get_policy
from app.ai.revision.instruction import RevisionInstruction
from app.ai.verification.draft_verifier import (
    AMOUNT_PATTERN,
    DATE_PATTERN,
    DOCUMENT_NUMBER_PATTERN,
    LEGISLATION_PATTERN,
    STRUCTURE_CHECKS,
    VerificationReport,
    _fold,
    _findall,
)
from app.ai.verification.normalizers import canonical_for_kind
from app.core.config import settings
from app.observability.ai_metrics import REVISION_CONFLICTS

logger = logging.getLogger(__name__)

ConflictKind = Literal[
    "mevzuat_dayanaksiz",
    "mevzuat_celiskisi",
    "kaynak_celiskisi",
    "yapisal_ihlal",
    "kisisel_veri",
    "belirsizlik",
]
Severity = Literal["critical", "major", "minor"]

#: Length cap on every free-text field -- a conflict finding is a pointer to
#: a problem, not a place to reproduce the draft or a large mevzuat excerpt.
_FIELD_LIMIT = 300


class ConflictFinding(BaseModel):
    """One concrete clash between the applied instruction and mevzuat/kaynak."""

    kind: ConflictKind
    severity: Severity
    detail: str = Field(max_length=_FIELD_LIMIT)
    instruction_fragment: str = Field(default="", max_length=200)
    evidence: str = Field(default="", max_length=_FIELD_LIMIT)
    source: Literal["deterministic", "llm"]


class ConflictReport(BaseModel):
    """The merged outcome of both audit layers."""

    conflicts: list[ConflictFinding] = Field(default_factory=list)
    requires_human_approval: bool = False
    #: Invariant, not a decision: this module never suppresses or reverts an
    #: edit, so this is always True. Kept as an explicit field (rather than
    #: only documented) so a caller can assert on it directly.
    applied_anyway: bool = True
    notes: str = ""


class LlmConflictFinding(BaseModel):
    """One LLM-reported conflict. No field may carry draft text."""

    kind: ConflictKind
    severity: Severity
    detail: str = Field(max_length=_FIELD_LIMIT)
    evidence: str = Field(default="", max_length=_FIELD_LIMIT)


class ConflictAssessment(BaseModel):
    """The conflict auditor's structured response."""

    conflicts: list[LlmConflictFinding] = Field(default_factory=list, max_length=5)
    rationale: str = Field(default="", max_length=400)


#: Phrases asking to remove a structural element, mapped to the
#: STRUCTURE_CHECKS id it names (see draft_verifier.STRUCTURE_CHECKS).
_REMOVAL_HINTS: dict[str, str] = {
    "kapanisi kaldir": "kapanis",
    "kapanisi sil": "kapanis",
    "kapanis cumlesini sil": "kapanis",
    "konu satirini sil": "konu",
    "konuyu sil": "konu",
    "konuyu kaldir": "konu",
    "imzayi cikar": "imza",
    "imzayi kaldir": "imza",
    "imzayi sil": "imza",
    "sayiyi sil": "sayi",
    "sayiyi kaldir": "sayi",
    "tarihi kaldir": "tarih",
    "tarihi sil": "tarih",
}

#: (pattern, canonical kind, Turkish label) triples checked for
#: instruction-vs-source contradictions. Institution is deliberately
#: excluded here -- names survive paraphrase (see draft_verifier's own
#: token-overlap escape hatch), so a textual mismatch is weak evidence of
#: an actual contradiction rather than a typed value with one true form.
_TYPED_CONFLICT_CHECKS: tuple[tuple, ...] = (
    (DATE_PATTERN, "tarih", "tarih"),
    (DOCUMENT_NUMBER_PATTERN, "sayı", "sayı"),
    (AMOUNT_PATTERN, "tutar", "tutar"),
)


def _canonical_values(pattern, kind: str, text: str) -> dict[str, str]:
    """raw value -> canonical form, for every match that canonicalizes."""
    values: dict[str, str] = {}
    for raw_value in _findall(pattern, text):
        canonical = canonical_for_kind(kind, raw_value)
        if canonical:
            values[raw_value] = canonical
    return values


def _legislation_citations(text: str) -> set[str]:
    citations: set[str] = set()
    for value in _findall(LEGISLATION_PATTERN, text):
        canonical = canonical_for_kind("mevzuat", value)
        if canonical:
            citations.add(canonical)
    return citations


def _fragment(text: str, limit: int = 200) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def detect_conflicts_deterministic(
    *,
    instruction: RevisionInstruction,
    context: str,
    source_document: str,
    report: VerificationReport,
) -> list[ConflictFinding]:
    """Free, reproducible checks for an applied instruction's contradictions.

    Args:
        instruction: The parsed revision instruction (already applied).
        context: The (possibly re-retrieved) legislation context the
            revision was grounded in.
        source_document: The incoming document the draft responds to.
        report: The deterministic verification report for the *revised*
            draft -- used for its ``missing_structure`` and
            ``instruction_only_claims``.

    Returns:
        Every deterministic finding, unordered.
    """
    findings: list[ConflictFinding] = []
    raw = instruction.raw
    fragment = _fragment(raw)

    # 1. mevzuat_dayanaksiz -- a law/article citation the mevzuat context
    # does not contain.
    instruction_citations = _legislation_citations(raw)
    if instruction_citations:
        context_citations = _legislation_citations(context)
        for citation in sorted(instruction_citations - context_citations):
            findings.append(
                ConflictFinding(
                    kind="mevzuat_dayanaksiz",
                    severity="major",
                    detail=(
                        f"Talimatta geçen '{citation}' atfı doğrulanmış mevzuat "
                        "bağlamında bulunamadı."
                    ),
                    instruction_fragment=fragment,
                    evidence=_fragment(context, _FIELD_LIMIT) or "Mevzuat bağlamı boş.",
                    source="deterministic",
                )
            )

    # 2. kaynak_celiskisi -- a typed value in the instruction that clashes
    # with the source document's own value of the same kind.
    for pattern, kind, label in _TYPED_CONFLICT_CHECKS:
        instruction_values = _canonical_values(pattern, kind, raw)
        if not instruction_values:
            continue
        source_values = _canonical_values(pattern, kind, source_document)
        if not source_values:
            continue
        source_canonicals = set(source_values.values())
        for raw_value, canonical in instruction_values.items():
            if canonical in source_canonicals:
                continue
            example_raw = next(iter(source_values))
            findings.append(
                ConflictFinding(
                    kind="kaynak_celiskisi",
                    severity="critical",
                    detail=(
                        f"Talimattaki {label} ('{raw_value}') kaynak evraktaki "
                        f"{label} ('{example_raw}') ile çelişiyor."
                    ),
                    instruction_fragment=fragment,
                    evidence=_fragment(example_raw, _FIELD_LIMIT),
                    source="deterministic",
                )
            )

    # 3. yapisal_ihlal -- the instruction asked to remove a mandatory
    # element and the revised draft actually lost it.
    normalized = _fold(raw)
    missing = set(report.missing_structure)
    labels_by_id = {check_id: label for check_id, label, _pattern in STRUCTURE_CHECKS}
    seen_ids: set[str] = set()
    for hint, check_id in _REMOVAL_HINTS.items():
        if check_id in seen_ids or hint not in normalized:
            continue
        label = labels_by_id.get(check_id)
        if label in missing:
            seen_ids.add(check_id)
            findings.append(
                ConflictFinding(
                    kind="yapisal_ihlal",
                    severity="major",
                    detail=(
                        f"Talimat '{label}' unsurunun kaldırılmasını istedi; "
                        "resmî yazı formatı bu unsuru zorunlu kılar."
                    ),
                    instruction_fragment=fragment,
                    evidence="",
                    source="deterministic",
                )
            )

    # 4. kisisel_veri -- the instruction itself carries personal data.
    floor = get_policy().guardrail.pii_confidence_floor
    for pii in find_pii(raw):
        if pii.confidence >= floor:
            findings.append(
                ConflictFinding(
                    kind="kisisel_veri",
                    severity="major",
                    detail=f"Talimatta bir kişisel veri bulgusu tespit edildi ({pii.kind}).",
                    instruction_fragment=fragment,
                    evidence=pii.preview,
                    source="deterministic",
                )
            )

    # 5. mevzuat_celiskisi (weak form) -- an instruction-only claim of a
    # normative kind that neither source nor mevzuat backs.
    for claim in report.instruction_only_claims:
        if claim.kind in {"mevzuat", "kurum"}:
            findings.append(
                ConflictFinding(
                    kind="mevzuat_celiskisi",
                    severity="minor",
                    detail=(
                        f"Talimat, kaynakta veya mevzuatta doğrulanamayan bir "
                        f"{claim.kind} değeri getiriyor: '{claim.value}'."
                    ),
                    instruction_fragment=fragment,
                    evidence="",
                    source="deterministic",
                )
            )

    return findings


async def assess_conflicts_llm(
    agent: ConflictAuditorAgent,
    *,
    instruction: str,
    revised_draft: str,
    context: str,
    source_document: str,
    timeout_s: Optional[float] = None,
) -> list[ConflictFinding]:
    """Ask the fast-tier auditor for contradictions a regex cannot see.

    Never raises -- degrades to ``[]`` on timeout, a schema failure or any
    provider error, exactly like ``judge_draft``.

    Args:
        agent: A constructed ``ConflictAuditorAgent`` (fast-tier client).
        instruction: The user's revision instruction, already applied.
        revised_draft: The draft after the instruction was merged in.
        context: The legislation context the revision was grounded in.
        source_document: The incoming document the draft responds to.
        timeout_s: Hard timeout; defaults to
            ``settings.DRAFT_JUDGE_TIMEOUT_SECONDS`` (the same budget the
            draft judge uses -- this is a comparable single structured call).

    Returns:
        The LLM-sourced findings, or ``[]`` on any degradation.
    """
    timeout = timeout_s if timeout_s is not None else settings.DRAFT_JUDGE_TIMEOUT_SECONDS
    prompt = (
        "### KULLANICI TALİMATI (ZATEN UYGULANDI):\n"
        f"{instruction}\n\n"
        "### MEVZUAT BAĞLAMI:\n"
        f"{context or '(mevzuat bağlamı yok)'}\n\n"
        "### KAYNAK EVRAK:\n"
        f"{source_document or '(kaynak evrak yok)'}\n\n"
        "### UYGULANMIŞ HÂLDEKİ TASLAK:\n"
        f"{revised_draft}"
    )

    try:
        assessment: ConflictAssessment = await asyncio.wait_for(
            agent.run_structured(
                messages=prompt,
                response_model=ConflictAssessment,
                temperature=0.0,
                max_retries=1,
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Conflict auditor timed out after %.0fs; degrading.", timeout)
        return []
    except Exception:
        logger.exception("Conflict auditor call failed; degrading.")
        return []

    return [
        ConflictFinding(
            kind=finding.kind,
            severity=finding.severity,
            detail=finding.detail,
            instruction_fragment=_fragment(instruction),
            evidence=finding.evidence,
            source="llm",
        )
        for finding in assessment.conflicts
    ]


def merge_conflicts(
    deterministic: list[ConflictFinding], llm: list[ConflictFinding]
) -> ConflictReport:
    """Combine both layers into one report, deduped and Turkish-noted.

    Args:
        deterministic: Findings from ``detect_conflicts_deterministic``.
        llm: Findings from ``assess_conflicts_llm`` (``[]`` when skipped or
            degraded).

    Returns:
        The merged report. ``applied_anyway`` is always True -- see the
        module docstring.
    """
    merged: dict[tuple[str, str], ConflictFinding] = {}
    _SEVERITY_RANK = {"minor": 0, "major": 1, "critical": 2}

    for finding in (*deterministic, *llm):
        key = (finding.kind, _fold(finding.instruction_fragment or finding.detail))
        existing = merged.get(key)
        if existing is None or _SEVERITY_RANK[finding.severity] > _SEVERITY_RANK[existing.severity]:
            merged[key] = finding

    conflicts = list(merged.values())
    for finding in conflicts:
        REVISION_CONFLICTS.labels(
            kind=finding.kind, severity=finding.severity, source=finding.source
        ).inc()

    requires_approval = any(f.severity in {"critical", "major"} for f in conflicts)
    if conflicts:
        notes = (
            f"{len(conflicts)} adet talimat-mevzuat/kaynak çelişkisi tespit edildi; "
            "talimat yine de uygulandı."
        )
    else:
        notes = "Talimat ile mevzuat/kaynak arasında bir çelişki tespit edilmedi."

    return ConflictReport(
        conflicts=conflicts,
        requires_human_approval=requires_approval,
        applied_anyway=True,
        notes=notes,
    )
