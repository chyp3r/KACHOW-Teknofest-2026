"""Post-processing for the assist step's reply before it reaches the user.

``assert_no_prompt_leak`` already runs as a ``BaseAgent`` validator for the
writer/reviser/classifier agents (see ``app.ai.agents.base``), and directly
inside ``flows.revise``'s single-call rewrite -- every path that generates
document text is checked. The assist step's streamed reply was the one path
that generated user-facing text with no check at all: a prompt-injection
line that survived scrubbing (extraction-time only, see
``app.ai.guardrails.injection``'s own docstring) into a tool result could
echo straight back to the user with nothing catching it.

Applied once, after the stream completes, rather than per-token: token
streaming is optimistic and the frontend already replaces the streamed text
with the final result once it arrives (see ``planning_graph``'s SSE event
docs), so there is no cost to checking the whole reply at once instead of
fragmenting it mid-word waiting on a per-chunk check.
"""

import logging

from app.ai.guardrails.injection import GuardrailViolation, assert_no_prompt_leak

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "Bu yanıt bir güvenlik kontrolünden geçemediği için gösterilemiyor. "
    "Sorunuzu farklı bir şekilde tekrar sorar mısınız?"
)


def build_response(reply: str) -> tuple[str, bool]:
    """Validate and finalise an assist reply.

    Args:
        reply: The raw, already-streamed assist reply.

    Returns:
        A ``(text, flagged)`` pair. ``text`` is ``reply`` unchanged when it
        passes the check, or :data:`FALLBACK_REPLY` when it doesn't.
        ``flagged`` reports which happened, for the caller to log/record.
    """
    if not reply:
        return reply, False
    try:
        assert_no_prompt_leak(reply)
    except GuardrailViolation:
        logger.warning("Assist reply flagged by the prompt-leak guardrail; replaced.")
        return FALLBACK_REPLY, True
    return reply, False
