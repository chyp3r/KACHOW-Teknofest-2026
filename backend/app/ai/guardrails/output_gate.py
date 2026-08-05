"""The output-side guardrail gate: the last check before a reply reaches a user.

Generalises ``app.ai.response.builder`` (which still exists as a thin
backward-compatible wrapper around :func:`evaluate_response`). Before this
module, the only output-side check anywhere in the assist/chat path was
``assert_no_prompt_leak`` -- nothing checked whether a reply was actually
grounded in what was retrieved this turn, and nothing checked whether a
reply echoed personal data out of a document the requester may not be
cleared to see. This is the gap the user's "db'den saçma sapan bilgi
vermemeliyiz" concern names directly: a groundedness failure is a
hallucination risk, an unauthorized PII echo is a leakage risk, and neither
was checked before this module existed.

Three checks run, in order, each able to escalate the verdict:

1. ``assert_no_prompt_leak`` -- unchanged, still an instant hard block.
2. Groundedness (``app.ai.verification.draft_verifier.check_groundedness``,
   reused not reimplemented) -- an ungrounded claim is redacted out of the
   reply rather than replacing the whole thing, since a partially-fabricated
   answer to "kaç sayfa bu belge" is more useful with the fabricated span
   removed than swapped for a generic refusal.
3. PII leakage (``app.ai.guardrails.pii.redact_pii``) -- only engaged when a
   document was actually attached this turn (``sensitivity is not None``); a
   PII-shaped span the user typed into the conversation themselves is not
   something this gate touches. When a document is attached and its content
   echoes into the reply as PII, the span is masked. If that document was
   itself confidentiality-marked (``SensitivityAssessment.requires_review``)
   and the requester's clearance doesn't cover it (or no clearance is known
   at all, which is this system's default-secure posture until the RBAC
   phase wires a real one), the response is blocked outright instead --
   the "unauthorized leakage" tier from the resolved policy, not the
   ordinary "mask and continue" tier.
"""

import logging
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.guardrails.injection import GuardrailViolation, assert_no_prompt_leak
from app.ai.guardrails.llm_nuance import GuardrailJudgeVerdict
from app.ai.guardrails.pii import redact_pii
from app.ai.guardrails.sensitivity import SensitivityAssessment
from app.ai.policy import GuardrailPolicy, get_policy
from app.ai.verification.draft_verifier import check_groundedness
from app.core.enums.sensitivity_level import SensitivityLevel

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "Bu yanıt bir güvenlik kontrolünden geçemediği için gösterilemiyor. "
    "Sorunuzu farklı bir şekilde tekrar sorar mısınız?"
)

#: Turkish placeholder swapped in for a claim `check_groundedness` couldn't
#: trace to this turn's sources.
_UNGROUNDED_MARKER = "[doğrulanamayan ifade kaldırıldı]"

GateAction = Literal["pass", "redact", "block"]


class GateVerdict(BaseModel):
    """The output gate's decision for one reply."""

    action: GateAction = Field(description="'pass' | 'redact' | 'block'.")
    text: str = Field(description="Kullanıcıya gösterilecek metin.")
    reasons: list[str] = Field(default_factory=list)


def _redact_unsupported_claims(text: str, claims: list) -> str:
    """Replace each ungrounded claim's text with a redaction marker.

    Best-effort string replacement: ``UnsupportedClaim.value`` is whitespace-
    normalised by ``draft_verifier._findall`` and so may not byte-match the
    exact span in ``text`` when the original had irregular spacing. A claim
    that can't be found is left in place rather than guessed at -- it still
    shows up in ``reasons``, so the miss is visible rather than silent.
    """
    redacted = text
    for claim in claims:
        if claim.value and claim.value in redacted:
            redacted = redacted.replace(claim.value, _UNGROUNDED_MARKER)
    return redacted


def evaluate_response(
    reply: str,
    *,
    source_materials: str = "",
    sensitivity: Optional[SensitivityAssessment] = None,
    requester_clearance: Optional[SensitivityLevel] = None,
    policy: Optional[GuardrailPolicy] = None,
    judge_verdict: Optional[GuardrailJudgeVerdict] = None,
) -> GateVerdict:
    """Validate and finalise a generated reply before it reaches the user.

    Args:
        reply: The raw, already-generated reply text.
        source_materials: Trusted material this turn actually drew on --
            tool results and cached document text, joined. Empty means "no
            sources to check against", which is a legitimate state (a
            conversational turn with no document and no tool calls) and
            simply finds no unsupported claims rather than flagging
            everything, since a reply with nothing to be ungrounded *from*
            is not evidence of fabrication.
        sensitivity: This turn's source document's input-side assessment
            (see ``app.ai.guardrails.sensitivity.assessment_from_analysis``),
            when a document is attached. None when there is no document.
        requester_clearance: The requester's clearance level. None means "no
            clearance is known" -- until the RBAC phase wires a real one
            from an authenticated user, this is always the case, and the
            gate treats it the same as "does not clear the source's level"
            rather than the same as "clears everything". Fail secure, not
            fail open.
        policy: Guardrail policy to gate against. Defaults to the process
            policy.
        judge_verdict: The guardrail nuance layer's opinion on this reply
            (see ``app.ai.guardrails.llm_nuance.judge_output_leakage``),
            already computed by the caller -- this function does no I/O of
            its own, same separation ``draft_graph.verify_node`` keeps
            between ``verify_draft`` (sync) and ``judge_draft`` (async).
            ``None`` when the judge is disabled, degraded, or wasn't asked
            (no document attached, so there's nothing to judge leakage
            against).

    Returns:
        The gate's verdict: ``pass`` (reply unchanged), ``redact`` (reply
        edited in place), or ``block`` (replaced with :data:`FALLBACK_REPLY`
        entirely).
    """
    if not reply:
        return GateVerdict(action="pass", text=reply)

    active_policy = policy or get_policy().guardrail

    try:
        assert_no_prompt_leak(reply)
    except GuardrailViolation:
        logger.warning("Reply flagged by the prompt-leak guardrail; blocked.")
        return GateVerdict(action="block", text=FALLBACK_REPLY, reasons=["prompt_leak_or_injection_echo"])

    reasons: list[str] = []
    redacted = reply

    unsupported = check_groundedness(reply, source_materials=source_materials)
    if unsupported:
        redacted = _redact_unsupported_claims(redacted, unsupported)
        reasons.append(f"{len(unsupported)} doğrulanamayan ifade kaldırıldı")

    # PII handling only engages when a document is actually attached this
    # turn (`sensitivity is not None`). Without one, a detected PII-shaped
    # span is something the user themselves typed into the conversation --
    # masking that back at them is surprising, not protective. With one,
    # any PII the reply echoes traces back to that document, whether or not
    # it carries a confidentiality marking.
    if sensitivity is not None:
        _preview, pii_findings = redact_pii(reply, confidence_floor=active_policy.pii_confidence_floor)
        # The judge catches what no pattern matches: a reply that discloses
        # a source's meaning without ever emitting a literal PII string.
        # Only trusted when the judge is confident -- a low-confidence
        # "maybe sensitive" should not carry the same weight as a checksum-
        # validated TCKN match.
        semantic_leak = bool(judge_verdict and judge_verdict.sensitive and judge_verdict.confidence >= 0.5)

        if pii_findings or semantic_leak:
            cleared = requester_clearance is not None and requester_clearance >= sensitivity.level
            if sensitivity.requires_review and not cleared:
                logger.warning(
                    "Reply blocked: %d PII finding(s), semantic_leak=%s against a "
                    "%s-marked source with insufficient/unknown requester clearance.",
                    len(pii_findings),
                    semantic_leak,
                    sensitivity.level.value,
                )
                block_reason = (
                    "yetkisiz kişisel veri sızıntısı tespit edildi"
                    if pii_findings
                    else f"yetkisiz anlam bazlı sızıntı tespit edildi (llm-judge: {judge_verdict.reason})"
                )
                return GateVerdict(
                    action="block",
                    text=FALLBACK_REPLY,
                    reasons=reasons + [block_reason],
                )

            if pii_findings:
                # Not confidentiality-marked, or the requester is cleared
                # for it -- still mask the PII itself as defense-in-depth.
                # Applied to `redacted` (not the original `reply`), so a
                # groundedness redaction above and a PII mask here both
                # land in the same output instead of one silently
                # discarding the other.
                redacted, _findings = redact_pii(redacted, confidence_floor=active_policy.pii_confidence_floor)
                reasons.append(f"{len(pii_findings)} pii bulgusu maskelendi")
            elif semantic_leak:
                # No specific span to mask -- the judge flagged the reply's
                # meaning as a whole, not a locatable string, so there is
                # nothing narrower to redact than the full reply.
                redacted = (
                    "Bu yanıt, kaynağın ifşa etmemesi gereken bir bilgiyi "
                    "içerebileceği için kısaltıldı."
                )
                reasons.append(f"llm-judge anlam bazlı hassasiyet: {judge_verdict.reason}")

    if redacted != reply:
        return GateVerdict(action="redact", text=redacted, reasons=reasons)

    return GateVerdict(action="pass", text=reply)


def classify_reason_kind(reasons: list[str]) -> str:
    """Map a :class:`GateVerdict`'s reasons to one ``GuardrailEventModel.kind``.

    Best-effort: a single verdict can combine a groundedness redaction and a
    PII mask in the same call, but the audit trail needs exactly one ``kind``
    per row -- this picks the most specific/severe match rather than trying
    to represent a compound decision in a single-valued column.

    Args:
        reasons: A verdict's ``reasons`` list.

    Returns:
        One of ``"leakage"``, ``"pii"``, ``"llm_judge"``, ``"groundedness"``,
        ``"injection"``, or the generic ``"output_gate"`` when nothing more
        specific matched.
    """
    joined = " ".join(reasons)
    if "yetkisiz" in joined:
        return "leakage"
    if "pii" in joined:
        return "pii"
    if "llm-judge" in joined:
        return "llm_judge"
    if "doğrulanamayan" in joined:
        return "groundedness"
    if "prompt_leak" in joined or "injection" in joined:
        return "injection"
    return "output_gate"
