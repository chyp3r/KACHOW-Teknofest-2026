"""The guardrail nuance layer: an LLM judge for meaning, not pattern.

Same relationship ``app.ai.verification.llm_judge`` has to
``draft_verifier.verify_draft``: the deterministic guardrail layer (``pii.py``
regex+checksum, ``sensitivity.py``'s ``gizlilik_derecesi`` mapping,
``output_gate.py``'s claim-extraction groundedness check) catches everything
that has a structural shape. It cannot catch a document that reads as
sensitive only in meaning (a medical detail in a leave request's prose, a
whistleblower's identity implied by context in a complaint) or a reply that
leaks a confidential fact without ever emitting a literal PII string. Those
need reasoning, not string matching, so this module adds a single small
structured call to the fast-tier model for them -- the same trade this
codebase already made once for draft quality.

The judge is deliberately not allowed to re-emit the content it's judging:
``GuardrailJudgeVerdict.reason`` is length-capped, and a post-validation guard
rejects a verdict whose text strongly overlaps the judged content (same
technique as ``llm_judge._reject_draft_echo``). A model that echoes the
content back is not judging it, and asking it to try again just produces a
second echo -- so an echo is treated as a degraded call, not a retry.

Every entry point here fails open: a timeout, a schema failure, a provider
error, or a detected echo all return ``None``, and the caller falls back to
the deterministic-only verdict rather than blocking the request on a slow or
unavailable Ollama instance (the resolved policy decision -- available beats
exhaustive).
"""

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.policy import get_policy
from app.ai.verification.draft_verifier import _fold
from app.core.config import settings
from app.observability.ai_metrics import GUARDRAIL_JUDGE_FAILURES

logger = logging.getLogger(__name__)

#: Above this fraction of a verdict's own tokens appearing in the judged
#: content, treat the verdict as an echo rather than a judgement.
_ECHO_OVERLAP_THRESHOLD = get_policy().guardrail.judge_echo_overlap_threshold

#: Text longer than this is truncated before it reaches the prompt -- the
#: judge needs enough to reason about, not the whole document/reply verbatim
#: (which would also make an echo far more likely to slip past the guard).
_MAX_JUDGED_TEXT_CHARS = 4000


class GuardrailJudgeVerdict(BaseModel):
    """The guardrail judge's structured verdict. No field may carry judged content."""

    sensitive: bool = Field(
        description="İçerik anlam olarak hassas/sızıntı riski taşıyor mu."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=300, description="Kısa gerekçe; içerik metnini tekrar üretme.")


def _reject_echo(verdict: GuardrailJudgeVerdict, judged_text: str) -> bool:
    """Detect a verdict that echoes the judged content instead of judging it.

    Args:
        verdict: The candidate verdict.
        judged_text: The document or reply text it was supposed to assess.

    Returns:
        True when the verdict's reason overlaps the judged text too
        strongly to trust.
    """
    content_tokens = set(_fold(judged_text).split())
    if not content_tokens:
        return False

    reason_tokens = [token for token in _fold(verdict.reason).split() if len(token) > 2]
    if len(reason_tokens) < 6:
        return False

    overlap = sum(1 for token in reason_tokens if token in content_tokens) / len(reason_tokens)
    return overlap > _ECHO_OVERLAP_THRESHOLD


async def _run_judge(
    agent: GuardrailJudgeAgent,
    *,
    prompt: str,
    judged_text: str,
    timeout_s: Optional[float],
) -> Optional[GuardrailJudgeVerdict]:
    """Shared call/degrade path for both judgement tasks. Never raises.

    Args:
        agent: A constructed :class:`GuardrailJudgeAgent` (fast-tier client).
        prompt: The full task-specific prompt (see the two public functions
            below).
        judged_text: The raw text being judged, used only for the anti-echo
            check -- never sent back out in the verdict.
        timeout_s: Hard timeout; defaults to
            ``settings.GUARDRAIL_JUDGE_TIMEOUT_SECONDS``.

    Returns:
        The verdict, or ``None`` on timeout, a schema failure, a provider
        error, or a detected echo.
    """
    if not settings.GUARDRAIL_JUDGE_ENABLED:
        return None

    timeout = timeout_s if timeout_s is not None else settings.GUARDRAIL_JUDGE_TIMEOUT_SECONDS

    try:
        verdict: GuardrailJudgeVerdict = await asyncio.wait_for(
            agent.run_structured(
                messages=prompt,
                response_model=GuardrailJudgeVerdict,
                temperature=0.0,
                max_retries=1,
            ),
            timeout=timeout,
        )
        # Covers the echo check too, not just the call itself -- this
        # function promises never to raise, and a malformed/mocked verdict
        # (missing fields, wrong types) must degrade the same way a timeout
        # or provider error does, not propagate out and take the whole
        # calling node down with it.
        if _reject_echo(verdict, judged_text):
            logger.warning(
                "Guardrail judge verdict echoed the judged content; treating as degraded."
            )
            GUARDRAIL_JUDGE_FAILURES.labels(reason="echo").inc()
            return None
    except asyncio.TimeoutError:
        logger.warning("Guardrail judge timed out after %.0fs; degrading.", timeout)
        GUARDRAIL_JUDGE_FAILURES.labels(reason="timeout").inc()
        return None
    except Exception:
        logger.exception("Guardrail judge call failed; degrading.")
        GUARDRAIL_JUDGE_FAILURES.labels(reason="exception").inc()
        return None

    return verdict


async def judge_input_sensitivity(
    agent: GuardrailJudgeAgent,
    *,
    text: str,
    timeout_s: Optional[float] = None,
) -> Optional[GuardrailJudgeVerdict]:
    """Ask whether a document reads as sensitive in meaning, pattern or not.

    Args:
        agent: A constructed :class:`GuardrailJudgeAgent`.
        text: The document text to assess.
        timeout_s: Hard timeout override.

    Returns:
        The verdict, or ``None`` if the call degraded -- callers fall back
        to the deterministic ``SensitivityAssessment`` alone.
    """
    if not text.strip():
        return None

    truncated = text[:_MAX_JUDGED_TEXT_CHARS]
    prompt = (
        "GÖREV: GİRDİ HASSASİYET DEĞERLENDİRMESİ\n\n"
        "### DEĞERLENDİRİLECEK BELGE METNİ:\n"
        f"{truncated}"
    )
    return await _run_judge(agent, prompt=prompt, judged_text=truncated, timeout_s=timeout_s)


async def judge_output_leakage(
    agent: GuardrailJudgeAgent,
    *,
    reply: str,
    source_summary: str,
    timeout_s: Optional[float] = None,
) -> Optional[GuardrailJudgeVerdict]:
    """Ask whether a reply leaks a source's meaning without a literal PII string.

    Args:
        agent: A constructed :class:`GuardrailJudgeAgent`.
        reply: The generated reply to assess.
        source_summary: A short description of what the source material
            actually authorizes disclosing (e.g. the document's own summary)
            -- not the full source text, which would make almost any
            paraphrase look like a match.
        timeout_s: Hard timeout override.

    Returns:
        The verdict, or ``None`` if the call degraded -- callers fall back
        to the deterministic leakage check alone.
    """
    if not reply.strip():
        return None

    truncated = reply[:_MAX_JUDGED_TEXT_CHARS]
    prompt = (
        "GÖREV: ÇIKTI SIZINTI DEĞERLENDİRMESİ\n\n"
        "### KAYNAĞIN İZİN VERDİĞİ BİLGİ ÖZETİ:\n"
        f"{source_summary or '(özet yok)'}\n\n"
        "### DEĞERLENDİRİLECEK YANIT:\n"
        f"{truncated}"
    )
    return await _run_judge(agent, prompt=prompt, judged_text=truncated, timeout_s=timeout_s)
