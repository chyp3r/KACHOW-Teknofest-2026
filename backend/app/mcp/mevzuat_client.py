"""Low-level mevzuat-mcp operations shared by every caller that resolves a
legislation number to its current official text.

Extracted out of `app.ai.tools.mevzuat_tools` (the assistant's live lookup
tool) rather than duplicated for `app.ai.retrieval.mcp_mevzuat` (document
analysis's MCP-first retriever): both need the exact same two things --
resolve a `mevzuat_no` to a document id while skipping a repealed companion
entry, then fetch that id's full text -- and the repealed-marker trap is
subtle enough that it must have exactly one implementation.

Carries no timeout policy of its own. Each caller already has its own bound
to enforce (the assistant wraps one whole lookup in `MEVZUAT_MCP_TIMEOUT_SECONDS`;
the retriever bounds many concurrent per-law fetches differently) so the
`asyncio.wait_for` belongs at the call site, not duplicated in here.
"""

import logging
import re
from typing import Optional

from app.mcp.manager import mcp_manager
from app.mcp.registry import MEVZUAT_SERVER

logger = logging.getLogger(__name__)

#: Result-line markers for legislation that is no longer in force. The repealed
#: companion to a law carries the *same* number as the law itself, so number
#: matching alone does not separate them.
_REPEALED_MARKERS = ("Mülga", "MÜLGA", "YÜRÜRLÜKTEN KALDIRILMIŞ")


def text_of(result: object) -> str:
    """Read the text payload out of an MCP tool result.

    Args:
        result: Whatever `MCPManager.call_tool` returned.

    Returns:
        The first text content block, or an empty string.
    """
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return text
    return ""


def pick_document_id(search_output: str) -> Optional[str]:
    """Choose the best result's document id from a search response.

    The server returns Markdown-ish lines like
    ``- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: 102924``.

    Taking the first `mevzuatId` is wrong, and quietly so. Searching for 657
    returns "DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ"
    (mevzuat_id 335559) *above* the actual Devlet Memurları Kanunu (102924) --
    both legitimately numbered 657, one of them repealed. Quoting repealed text
    as current law is exactly the failure this project exists to avoid, so
    repealed entries are skipped and only fallen back to if nothing else
    matched.

    Args:
        search_output: Raw text of a `search_mevzuat` response.

    Returns:
        The chosen document id, or None when the response has no results.
    """
    fallback: Optional[str] = None
    for line in search_output.splitlines():
        match = re.search(r"mevzuatId:\s*(\d+)", line)
        if not match:
            continue
        if any(marker in line for marker in _REPEALED_MARKERS):
            fallback = fallback or match.group(1)
            continue
        return match.group(1)
    return fallback


async def resolve_mevzuat_id(mevzuat_no: str, mevzuat_tur: Optional[str] = None) -> Optional[str]:
    """Resolve a legislation number to its current document id.

    Tries the given type filter first (cheaper, and what excludes a repealed
    companion outright for most numbers), then retries unfiltered before
    giving up -- a numbered yönetmelik, tüzük or KHK has no match under a
    KANUN-only filter, and this project's own tool descriptions promise a
    numeric query is the reliable way to look one up.

    Args:
        mevzuat_no: Official legislation number.
        mevzuat_tur: Type filter to try first (e.g. "KANUN"), or None to
            search unfiltered from the start.

    Returns:
        The resolved document id, or None when nothing matches the number.
    """
    if mevzuat_tur:
        filtered = await mcp_manager.call_tool(
            MEVZUAT_SERVER,
            "search_mevzuat",
            {"mevzuat_no": mevzuat_no, "mevzuat_tur": mevzuat_tur, "page_size": 5},
        )
        document_id = pick_document_id(text_of(filtered))
        if document_id is not None:
            return document_id

    unfiltered = await mcp_manager.call_tool(
        MEVZUAT_SERVER, "search_mevzuat", {"mevzuat_no": mevzuat_no, "page_size": 5}
    )
    return pick_document_id(text_of(unfiltered))


async def fetch_mevzuat_text(mevzuat_id: str) -> str:
    """Fetch one law's full current text by its document id.

    Args:
        mevzuat_id: Document id, as resolved by `resolve_mevzuat_id`.

    Returns:
        The full text, or an empty string when the server returned nothing.
    """
    content = await mcp_manager.call_tool(
        MEVZUAT_SERVER, "get_mevzuat_content", {"mevzuat_id": mevzuat_id}
    )
    return text_of(content).strip()


async def resolve_and_fetch(
    mevzuat_no: str, mevzuat_tur: Optional[str] = None
) -> Optional[tuple[str, str]]:
    """Resolve a legislation number and fetch its current full text.

    Args:
        mevzuat_no: Official legislation number.
        mevzuat_tur: Type filter to try first, or None to search unfiltered.

    Returns:
        The document id and its text, or None when resolution or fetch found
        nothing.
    """
    document_id = await resolve_mevzuat_id(mevzuat_no, mevzuat_tur)
    if document_id is None:
        return None
    text = await fetch_mevzuat_text(document_id)
    if not text:
        return None
    return document_id, text
