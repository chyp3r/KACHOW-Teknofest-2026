"""Backward-compatible wrapper over the output gate.

``evaluate_response`` (``app.ai.guardrails.output_gate``) is the real gate
now: injection-echo check, groundedness, and PII-leakage, in one place. This
module's ``build_response``/``FALLBACK_REPLY`` are kept only because they
were the public surface every existing caller and test already used --
``planning_graph._run_assist`` now calls ``evaluate_response`` directly and
passes it real source materials and sensitivity context, which this
two-value wrapper has no room for.
"""

import logging

from app.ai.guardrails.output_gate import FALLBACK_REPLY, evaluate_response

logger = logging.getLogger(__name__)

__all__ = ["FALLBACK_REPLY", "build_response"]


def build_response(reply: str) -> tuple[str, bool]:
    """Validate and finalise a reply with no source/sensitivity context.

    Args:
        reply: The raw, already-generated reply.

    Returns:
        A ``(text, flagged)`` pair. ``text`` is ``reply`` unchanged when it
        passes every check, or the gate's edited/replacement text otherwise.
        ``flagged`` is True whenever the gate's action was not ``"pass"``.
    """
    verdict = evaluate_response(reply)
    if verdict.action != "pass":
        logger.warning("Reply flagged by the output gate (%s); replaced.", verdict.action)
    return verdict.text, verdict.action != "pass"
