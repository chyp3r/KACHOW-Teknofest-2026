"""Live legislation lookup for the assistant, over MCP.

The committed corpus under `datasets/mevzuat/` holds seven laws and answers every
scored requirement with no network at all. It cannot answer a question about the
other several thousand, which is what this is for: a question the corpus does not
cover reaches mevzuat.gov.tr instead of getting a confident wrong answer or a
flat "bulunamadı".

Three properties, all deliberate:

* **Additive only.** This never gates a compliance decision. `check_required_fields`
  is set subtraction over a rule table with hard-coded article numbers, and the
  analysis pipeline never calls this module -- that is what keeps the same evrak
  producing byte-identical output on every run.
* **Second, not first.** `search_legislation` (the local corpus) is registered
  ahead of this one, so the model reaches for the offline path by default and this
  is the escalation.
* **Failure is an answer.** An unreachable government site returns the same
  "not found" string the local tool returns, never an exception. A chat turn must
  not 500 because a third-party site is down, and the tool description tells the
  model the result is authoritative *when present* rather than promising it.
"""

import asyncio
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec
from app.core.config import settings
from app.mcp.manager import mcp_manager
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

NOT_FOUND = "İlgili bir mevzuat maddesi bulunamadı."

#: How many search hits to resolve to full text. Each resolution is a second
#: round-trip to the government site, and the assistant summarises rather than
#: quotes at length, so one good hit beats three partial ones.
RESOLVE_LIMIT = 1
#: Characters of legislation text handed back to the model. A whole law can run to
#: half a million characters (657 does), which would blow the context window.
EXCERPT_CHAR_LIMIT = 6000


class SearchLiveLegislationArgs(BaseModel):
    """Arguments for the ``search_legislation_live`` tool."""

    query: str = Field(
        description=(
            "Aranacak mevzuatın adı veya numarası (örn. '657', "
            "'Tebligat Kanunu'). Konu değil, mevzuatın kendisi aranır."
        )
    )


#: Result-line markers for legislation that is no longer in force. The repealed
#: companion to a law carries the *same* number as the law itself, so number
#: matching alone does not separate them.
_REPEALED_MARKERS = ("Mülga", "MÜLGA", "YÜRÜRLÜKTEN KALDIRILMIŞ")


def _pick_document_id(search_output: str) -> Optional[str]:
    """Choose the best result's document id from a search response.

    The server returns Markdown-ish lines like
    ``- [657] DEVLET MEMURLARI KANUNU (Kanunlar) | mevzuatId: 102924``.

    Taking the first `mevzuatId` is wrong, and quietly so. Searching for 657
    returns "DEVLET MEMURLARI KANUNUNUN YÜRÜRLÜKTEN KALDIRILMIŞ HÜKÜMLERİ"
    (mevzuat_id 335559) *above* the actual Devlet Memurları Kanunu (102924) --
    both legitimately numbered 657, one of them repealed. Quoting repealed text
    as current law is exactly the failure this project exists to avoid, so
    repealed entries are skipped and only fall back to if nothing else matched.

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


def _text_of(result: object) -> str:
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


async def _lookup(query: str) -> str:
    """Resolve a legislation name or number to its official text.

    Args:
        query: Legislation name or number.

    Returns:
        An excerpt of the official text, or `NOT_FOUND`.
    """
    # Numeric queries are the reliable path. Resolving by title returns the wrong
    # document often enough to matter -- searching "Devlet Memurları Kanunu" puts
    # law 7417, a 2022 act *amending* 657, at the top while 657 itself does not
    # appear at all. Same trap `scripts/fetch_mevzuat_corpus.py` documents.
    stripped = query.strip()
    arguments: dict[str, object] = {"page_size": 5}
    if stripped.isdigit():
        # Type-filtered as well as numbered. Without the filter, 657 returns its
        # repealed-provisions companion first -- the filter drops that entry
        # entirely, and _pick_document_id guards the name-search path where no
        # equivalent filter applies.
        arguments["mevzuat_no"] = stripped
        arguments["mevzuat_tur"] = "KANUN"
    else:
        arguments["mevzuat_adi"] = stripped

    found = await mcp_manager.call_tool(MEVZUAT_SERVER, "search_mevzuat", arguments)
    document_id = _pick_document_id(_text_of(found))
    if document_id is None:
        return NOT_FOUND

    content = await mcp_manager.call_tool(
        MEVZUAT_SERVER, "get_mevzuat_content", {"mevzuat_id": document_id}
    )
    text = _text_of(content).strip()
    if not text:
        return NOT_FOUND

    if len(text) > EXCERPT_CHAR_LIMIT:
        text = text[:EXCERPT_CHAR_LIMIT] + "\n\n[... metin kısaltıldı ...]"
    return f"(Kaynak: mevzuat.gov.tr, mevzuat_id={document_id})\n\n{text}"


def build_live_legislation_tools() -> list[ToolSpec]:
    """Build the live legislation tool, when the MCP server is configured.

    Returns:
        A single-element list when `MEVZUAT_MCP_ENABLED` is on and the server is
        registered, otherwise an empty list -- so the model is never offered a
        tool that cannot run.
    """
    if not is_registered(MEVZUAT_SERVER):
        return []

    async def _search_legislation_live(query: str) -> str:
        try:
            return await asyncio.wait_for(
                _lookup(query), timeout=settings.MEVZUAT_MCP_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Live legislation lookup timed out after %ss for %r.",
                settings.MEVZUAT_MCP_TIMEOUT_SECONDS,
                query,
            )
            return NOT_FOUND
        except Exception:
            # Degrades to the same string the local tool returns on failure: an
            # unreachable government site is a "no result", not a broken chat.
            logger.exception("Live legislation lookup failed for %r.", query)
            return NOT_FOUND

    return [
        ToolSpec(
            name="search_legislation_live",
            description=(
                "Resmî mevzuat veritabanından (mevzuat.gov.tr) bir kanun veya "
                "yönetmeliğin güncel tam metnini getirir. Yalnızca "
                "search_legislation yerel korpusta yanıt bulamadığında kullan; "
                "mevzuatı numarasıyla aramak (örn. '657') adıyla aramaktan daha "
                "güvenilirdir."
            ),
            args_schema=SearchLiveLegislationArgs,
            handler=_search_legislation_live,
        )
    ]
