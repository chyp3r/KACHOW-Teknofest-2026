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

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec
from app.core.config import settings
from app.mcp.manager import mcp_manager
from app.mcp.mevzuat_client import fetch_mevzuat_text, pick_document_id, resolve_and_fetch, text_of
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

NOT_FOUND = "İlgili bir mevzuat maddesi bulunamadı."

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
    if stripped.isdigit():
        # KANUN first (cheaper, and what excludes 657's repealed companion
        # outright), retrying unfiltered before giving up -- this tool's own
        # description promises "kanun veya yönetmeliğin" and tells the model a
        # numeric query is the reliable one, so a numbered yönetmelik, tüzük or
        # KHK must not dead-end here just because the first attempt only asked
        # for KANUN. resolve_and_fetch and the retriever in
        # app.ai.retrieval.mcp_mevzuat share this exact resolution logic.
        resolved = await resolve_and_fetch(stripped, "KANUN")
    else:
        by_name = await mcp_manager.call_tool(
            MEVZUAT_SERVER, "search_mevzuat", {"mevzuat_adi": stripped, "page_size": 5}
        )
        document_id = pick_document_id(text_of(by_name))
        resolved = None
        if document_id is not None:
            text = await fetch_mevzuat_text(document_id)
            resolved = (document_id, text) if text else None

    if resolved is None:
        return NOT_FOUND
    document_id, text = resolved

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
    # Both conditions, not just registration: today `register_servers()` is the
    # only caller of `mcp_manager.register_server`, and it already gates on this
    # same flag, so checking is_registered() alone happens to agree with the
    # flag. Checking both directly here removes the dependency on that being the
    # only registration path ever added, rather than leaving it as a fact a
    # future caller could silently invalidate.
    if not settings.MEVZUAT_MCP_ENABLED or not is_registered(MEVZUAT_SERVER):
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
