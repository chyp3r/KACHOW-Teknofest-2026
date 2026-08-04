"""Generic ``ContextBlock`` compressors.

Each function has the ``Compressor`` shape (``(text, budget_tokens) ->
text``) from ``app.ai.context.builder`` and is provider-agnostic: it works
in characters, using ``CHARS_PER_TOKEN_TR`` to translate a token budget into
a character one, since the block itself doesn't have access to the active
client's exact estimator.
"""

from app.ai.llms.base import CHARS_PER_TOKEN_TR

#: Marker inserted between the surviving head and tail, matching the one
#: `document_analysis_graph._trim_for_extraction` already uses for the same
#: purpose -- a reader (human or model) seeing it once already knows what it
#: means.
ELISION_MARKER = "\n\n[... içeriğin orta kısmı kısaltıldı ...]\n\n"


def truncate_with_marker(text: str, budget_tokens: int) -> str:
    """Keep the head and tail of `text`, eliding the middle.

    A document's header and signature/closing block carry the fields most
    prompts need; the middle is the part safest to lose when something has
    to give. Splits the available characters evenly between head and tail.

    Args:
        text: The text to shrink.
        budget_tokens: The token budget to fit into.

    Returns:
        `text` unchanged if it already fits, otherwise head+tail elided to
        approximately `budget_tokens`.
    """
    budget_chars = max(0, int(budget_tokens * CHARS_PER_TOKEN_TR))
    marker_chars = len(ELISION_MARKER)

    if len(text) <= budget_chars:
        return text
    if budget_chars <= marker_chars:
        return text[:budget_chars]

    remaining = budget_chars - marker_chars
    head_chars = remaining // 2
    tail_chars = remaining - head_chars
    return f"{text[:head_chars]}{ELISION_MARKER}{text[-tail_chars:] if tail_chars else ''}"
