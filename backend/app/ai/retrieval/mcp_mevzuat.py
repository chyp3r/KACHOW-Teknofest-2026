"""MCP-first legislation retrieval for document analysis.

`mevzuat-mcp` exposes a *catalog* search (`search_mevzuat`, by law number or
title) and a full-text fetch (`get_mevzuat_content`) -- not a content/topic
search. `_build_mevzuat_query` (document_analysis_graph.py) builds a
keyword-dense *topic* string, which is the wrong shape for a catalog title
search. So "MCP-first" here means: fetch the current text of the same small,
curated set of laws the committed corpus already holds (by number, the
reliable lookup path -- see `app.mcp.mevzuat_client`), then rank that live
text with the same query the local retriever would have used, via an
in-memory BM25 index built fresh from the fetch. `HybridRetriever` (Qdrant,
dense+sparse) stays the local fallback and the only source when
`MEVZUAT_SOURCE="local"`.

Never touches compliance. `check_required_fields` is set subtraction over a
rule table with hard-coded article numbers; nothing in this module is on
that path.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from langchain_core.documents import Document

from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.policy import get_policy
from app.ai.retrieval.bm25 import BM25Retriever
from app.core.config import settings
from app.mcp.mevzuat_client import resolve_and_fetch
from app.mcp.registry import MEVZUAT_SERVER, is_registered

logger = logging.getLogger(__name__)

#: Sourced from ChunkingPolicy.mevzuat_* rather than a local literal --
#: must match scripts/index_mevzuat.py's parameters for the local corpus.
#: Not because the two indexes are ever compared directly (they are not;
#: each source is ranked independently), but because a mismatch here would
#: give the live path passages of a different granularity than the one
#: suggest_mevzuat's excerpt budget and prompt were tuned against. See
#: ChunkingPolicy's own docstring for why this pair is kept separate from
#: the Document Q&A pair.
CHUNK_SIZE = get_policy().chunking.mevzuat_chunk_size
CHUNK_OVERLAP = get_policy().chunking.mevzuat_chunk_overlap


@dataclass(frozen=True)
class _LegislationRef:
    """One curated law to keep fresh over MCP.

    number/kind mirror scripts/fetch_mevzuat_corpus.py's CORPUS exactly (same
    curation, same reason each entry was chosen -- see that file's docstring
    and its per-entry `why`). Duplicated rather than imported: that script
    lives at the repo root and reaches into the backend package via a
    sys.path hack for a one-off dev-time fetch, and importing a runtime
    module the other direction would make a bigger cross-boundary dependency
    than either duplicate list.
    """

    number: str
    kind: str
    title: str


CURATED_LEGISLATION: tuple[_LegislationRef, ...] = (
    _LegislationRef(
        "2646", "CB_YONETMELIK",
        "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik",
    ),
    _LegislationRef("3071", "KANUN", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    _LegislationRef("4982", "KANUN", "Bilgi Edinme Hakkı Kanunu"),
    _LegislationRef("657", "KANUN", "Devlet Memurları Kanunu"),
    _LegislationRef("6698", "KANUN", "Kişisel Verilerin Korunması Kanunu"),
    _LegislationRef("7201", "KANUN", "Tebligat Kanunu"),
    _LegislationRef("5070", "KANUN", "Elektronik İmza Kanunu"),
)


class McpMevzuatRetriever:
    """Legislation retrieval backed by live MCP fetches, ranked in memory.

    `retrieve()` never performs network I/O itself -- it only reads whatever
    `warm_up()` last built. This is deliberate: `retrieve_mevzuat_node` runs
    inside a per-request node budget (25s at balanced, 15s at fast -- see
    `app.ai.policy.schema`), and a cold fetch of seven laws over a
    playwright-backed MCP server has no guarantee of finishing inside that
    window. Keeping the fetch entirely off the request path is what makes
    this safe to default to; `warm_up()` is meant to be awaited once, from
    the same best-effort startup path that already warms the LLM clients and
    compiles the graphs (see `app.lifespan`).
    """

    def __init__(self) -> None:
        self._index: Optional[BM25Retriever] = None

    @property
    def is_warm(self) -> bool:
        """Whether a usable index is currently loaded."""
        return self._index is not None

    async def warm_up(self) -> None:
        """Fetch every curated law and (re)build the in-memory index.

        Best-effort per law: one law failing to resolve or fetch does not
        block the others, and the index is rebuilt from whatever succeeded.
        Only a complete failure (zero laws fetched) leaves no index -- in
        which case `retrieve()` reports not-warm and the caller falls back to
        the local corpus.
        """
        if not is_registered(MEVZUAT_SERVER):
            logger.info(
                "Mevzuat MCP server is not registered; MCP-first retrieval "
                "will stay on the local corpus."
            )
            return

        results = await asyncio.gather(
            *(self._fetch_one(ref) for ref in CURATED_LEGISLATION),
            return_exceptions=True,
        )

        chunker = RecursiveChunker(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        chunks: list[Document] = []
        failures = 0
        for ref, result in zip(CURATED_LEGISLATION, results):
            if isinstance(result, BaseException):
                failures += 1
                logger.warning(
                    "MCP fetch failed for %s (%s): %s", ref.number, ref.title, result
                )
                continue
            document_id, text = result
            law_chunks = await chunker.split_text(text)
            for chunk in law_chunks:
                chunk.metadata = {
                    **chunk.metadata,
                    "mevzuat": ref.title,
                    "source": f"mcp:{document_id}",
                }
            chunks.extend(law_chunks)

        if not chunks:
            logger.warning(
                "MCP-first legislation warm-up fetched nothing (%d/%d laws "
                "failed); staying on the local corpus until the next warm-up.",
                failures,
                len(CURATED_LEGISLATION),
            )
            return

        index = BM25Retriever()
        index.index_documents(chunks)
        self._index = index
        logger.info(
            "MCP-first legislation index warm: %d chunk(s) from %d/%d law(s).",
            len(chunks),
            len(CURATED_LEGISLATION) - failures,
            len(CURATED_LEGISLATION),
        )

    async def _fetch_one(self, ref: _LegislationRef) -> tuple[str, str]:
        """Resolve and fetch one curated law, raising on any failure.

        Bounded by the same per-lookup timeout the assistant's live tool
        uses: all seven laws fetch concurrently, so without this bound one
        hung call would hold the other six's results hostage for however
        long asyncio.gather takes to notice (up to the whole startup warm-up
        budget), instead of the usual single-lookup cap.

        Raises:
            RuntimeError: When the law could not be resolved or fetched.
            asyncio.TimeoutError: When it did not finish in time.
        """
        resolved = await asyncio.wait_for(
            resolve_and_fetch(ref.number, ref.kind),
            timeout=settings.MEVZUAT_MCP_TIMEOUT_SECONDS,
        )
        if resolved is None:
            raise RuntimeError(f"{ref.number} ({ref.title}) resolved to nothing")
        return resolved

    async def retrieve(self, query: str, limit: int = 5) -> list[Document]:
        """Rank the warm in-memory index against a query.

        Args:
            query: Search query (the same deterministic string the local
                retriever would receive).
            limit: Maximum documents to return.

        Returns:
            Ranked excerpts, or an empty list when no index is warm yet --
            never performs network I/O.
        """
        if self._index is None:
            return []
        return await self._index.retrieve(query, limit)


class FallbackMevzuatRetriever:
    """Tries a primary retriever, falls back to a secondary on failure or emptiness.

    Duck-types `HybridRetriever`'s `async retrieve(query, limit) ->
    list[Document]` interface, so `retrieve_mevzuat_node` needs no changes at
    all to use either source -- the strategy lives entirely here, at the
    dependency-injection boundary (see `app.api.dependency.get_mevzuat_retriever`).

    An empty *successful* primary result also falls through to the
    secondary, not just an exception: MCP-first ranks the same curated set of
    laws the local corpus holds, over BM25 alone (no dense half, since
    building a request-time embedding index would defeat the point of
    staying off the network path) -- so a query the dense half of the local
    retriever would have caught is exactly where falling through helps most.
    """

    def __init__(self, primary, fallback) -> None:
        self._primary = primary
        self._fallback = fallback

    async def retrieve(self, query: str, limit: int = 5) -> list[Document]:
        try:
            documents = await self._primary.retrieve(query, limit)
        except Exception:
            logger.warning("MCP-first legislation retrieval failed; falling back to local corpus.", exc_info=True)
            documents = []

        if documents:
            return documents
        return await self._fallback.retrieve(query, limit)

    async def warm_up(self) -> None:
        """Best-effort passthrough to the primary's warm-up, if it has one."""
        warm_up = getattr(self._primary, "warm_up", None)
        if warm_up is None:
            return
        try:
            await warm_up()
        except Exception:
            logger.warning("MCP-first legislation warm-up failed; staying on local corpus.", exc_info=True)
