"""Conditional legislation re-retrieval for a revision.

``run_revise`` never re-classifies (see ``app.ai.workflows.revise``'s module
docstring) and, by default, never re-retrieves legislation either -- it
reuses ``active_draft.context``, frozen from when the draft was first
written. That is correct for a tone/length edit, which needs no new
grounding, but wrong for an instruction that asks the draft to reference a
law, article or institution the frozen context never covered.

``maybe_extend_context`` is the single deliberate exception: it runs only
when ``needs_reretrieval`` says the instruction actually introduces
normative content, degrades to the frozen context on any failure or
timeout, and never raises.
"""

import asyncio
import logging
import re
from typing import Any, Optional

from app.ai.revision.instruction import RevisionInstruction, needs_reretrieval
from app.ai.session.focus import DraftVersion
from app.core.config import settings
from app.observability.ai_metrics import REVISION_RETRIEVAL

logger = logging.getLogger(__name__)

#: Excerpts pulled per re-retrieval -- the same order of magnitude as
#: document_analysis_graph's own MEVZUAT_RESULT_LIMIT, small enough that an
#: extension does not dominate the frozen context it is appended to.
DEFAULT_RETRIEVAL_LIMIT = 5

_ALINTI_MARKER = re.compile(r"\[ALINTI (\d+)\]")


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_query(instruction: RevisionInstruction, active_draft: DraftVersion) -> str:
    """Compose the re-retrieval query from the instruction's own normative
    tokens plus the draft's known subject -- the same "literal tokens the
    corpus matches best" rationale as
    ``document_analysis_graph._build_mevzuat_query``, not a model rewrite."""
    fields = _coerce_fields(active_draft.classification)
    parts = [
        *instruction.normative_tokens,
        fields.get("konu") or "",
        active_draft.correspondence_type or "",
    ]
    query = " ".join(str(part) for part in parts if part).strip()
    return query or instruction.raw


def _next_index(frozen_context: str) -> int:
    numbers = [int(match) for match in _ALINTI_MARKER.findall(frozen_context)]
    return (max(numbers) + 1) if numbers else 1


def _render_new_excerpts(documents: list[Any], *, frozen_context: str, start_index: int) -> list[str]:
    """Render only the excerpts not already present in the frozen context.

    Dedup is a plain substring check against the frozen context's rendered
    text -- the frozen context was rendered from the same corpus by the same
    function (``document_analysis_graph._render_mevzuat_excerpts``), so an
    excerpt already present there appears verbatim.
    """
    rendered: list[str] = []
    index = start_index
    for document in documents:
        content = (document.page_content or "").strip()
        if not content or content in frozen_context:
            continue
        source = document.metadata.get("mevzuat", "bilinmiyor")
        rendered.append(f"[ALINTI {index}] (Kaynak: {source})\n{content}")
        index += 1
    return rendered


async def maybe_extend_context(
    *,
    instruction: RevisionInstruction,
    active_draft: DraftVersion,
    retriever: Optional[Any],
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
    timeout_s: Optional[float] = None,
) -> tuple[str, dict[str, Any]]:
    """Extend the draft's frozen legislation context if the instruction calls for it.

    Args:
        instruction: The parsed revision instruction.
        active_draft: The draft version being revised, whose ``context`` is
            the frozen legislation excerpts from when it was first written.
        retriever: A hybrid/mevzuat retriever exposing
            ``async def retrieve(query, limit) -> list[Document]``, or None
            to always skip (matches ``document_analysis_graph``'s own
            "no retriever configured" convention).
        limit: Excerpts to request.
        timeout_s: Hard timeout; defaults to
            ``settings.REVISION_RERETRIEVAL_TIMEOUT_SECONDS``.

    Returns:
        ``(context, meta)``. ``context`` is the frozen context unchanged
        when re-retrieval is skipped, times out, or fails, or the frozen
        context with newly found excerpts appended. ``meta`` describes what
        happened: ``{"decision": "skipped"|"extended"|"failed", "query": str,
        "added": int}``.
    """
    frozen_context = active_draft.context or ""

    if (
        not settings.REVISION_RERETRIEVAL_ENABLED
        or retriever is None
        or not needs_reretrieval(instruction)
    ):
        REVISION_RETRIEVAL.labels(decision="skipped").inc()
        return frozen_context, {"decision": "skipped", "query": "", "added": 0}

    query = _build_query(instruction, active_draft)
    timeout = timeout_s if timeout_s is not None else settings.REVISION_RERETRIEVAL_TIMEOUT_SECONDS

    try:
        async with asyncio.timeout(timeout):
            documents = await retriever.retrieve(query, limit=limit)
    except Exception:
        logger.exception("Revision re-retrieval failed; keeping the frozen context.")
        REVISION_RETRIEVAL.labels(decision="failed").inc()
        return frozen_context, {"decision": "failed", "query": query, "added": 0}

    new_excerpts = _render_new_excerpts(
        documents, frozen_context=frozen_context, start_index=_next_index(frozen_context)
    )
    if not new_excerpts:
        REVISION_RETRIEVAL.labels(decision="skipped").inc()
        return frozen_context, {"decision": "skipped", "query": query, "added": 0}

    new_block = "\n\n".join(new_excerpts)
    extended = f"{frozen_context}\n\n{new_block}" if frozen_context else new_block
    REVISION_RETRIEVAL.labels(decision="extended").inc()
    return extended, {"decision": "extended", "query": query, "added": len(new_excerpts)}
