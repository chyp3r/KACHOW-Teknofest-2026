"""Cross-encoder reranking: an optional second pass over RRF-fused hybrid
search hits.

Nothing in this codebase reranks today -- "reranking" is RRF (fused inside
Qdrant) plus, for examples specifically, ``ExampleRetriever``'s institution-
diversity filter and a char-budget trim. None of that is a relevance
judgement of query against candidate text; RRF only ever combines two
independent rankings (dense cosine, sparse BM25), it never looks at the two
together. A small cross-encoder that scores ``(query, candidate)`` pairs
jointly catches exactly the failures a fusion-only pipeline cannot: the
right chunk retrieved, but ranked outside the writer's top-``limit`` cut
(see ``DraftPolicy.source_chunk_count``/``style_example_count``) because
fusion, not relevance, put it there.

**Why an in-process ``sentence-transformers`` model, not another Ollama
model:** tried first (Workstream J7's original approach) -- three separate
Ollama-hosted Qwen3-Reranker-0.6B GGUF uploads were tested live, each
failing for a distinct, reproducible reason: one whose GGUF conversion
carries a classification head Ollama's backend cannot load at all
(``pooling_type``/``cls.output.weight`` in its ``/api/show`` model info,
rejected with "does not support generate"), and two others that load and
respond `200 OK` but produce degenerate output -- byte-identical, uniform
logprobs across the entire vocabulary regardless of prompt, verified
against a known-good model (``qwen3.5:4b``) returning normal, varied
logprobs on the exact same request shape. Not a request-format bug on this
side; the GGUF conversions themselves are broken. A small
``sentence-transformers`` cross-encoder sidesteps the whole GGUF/Ollama
serving question -- live-verified during development to correctly rank a
genuinely relevant Turkish passage far above irrelevant ones (see this
module's own PR description for that run).

Wired as an *optional collaborator* on ``HybridRetriever`` (see that
module), the same degrade-safe shape ``ExampleRetriever``/
``retrieve_source_chunks_node`` already use: a reranker failure -- an
unreachable model, an OOM, anything -- must never be able to turn an
optional relevance boost into a failed retrieval. ``rerank()`` never
raises.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

__all__ = ["BaseReranker", "CrossEncoderReranker"]


class BaseReranker(ABC):
    """Scores and reorders retrieved documents against a query."""

    @abstractmethod
    async def rerank(
        self, query: str, documents: list[Document], *, top_k: int
    ) -> list[Document]:
        """Return up to ``top_k`` of ``documents``, most relevant first.

        Never raises -- a failing implementation must return its best
        available ordering (typically the input order, truncated) rather
        than propagate.
        """
        raise NotImplementedError


class CrossEncoderReranker(BaseReranker):
    """``sentence-transformers`` ``CrossEncoder``-backed reranker.

    The model is loaded lazily, on the first ``rerank()`` call, and cached
    on the instance -- constructing this class (see ``app.api.dependency``)
    must not itself pay the model's load time/memory, only the first turn
    that actually reaches this collaborator does, and every turn after
    reuses the same loaded weights. Both the (blocking) load and the
    (CPU-bound) ``predict`` call run in a worker thread via
    ``asyncio.to_thread`` so neither blocks the event loop other requests
    share.
    """

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            # Imported here, not at module scope: sentence-transformers
            # (and its torch dependency) is only ever installed when
            # reranking is actually exercised (dev/eval image + a `pytest`
            # run that reaches this code path) -- the production image
            # never imports this module's real work at all when
            # `RerankPolicy.enabled` is False, matching the
            # `WITH_MEVZUAT_MCP=0` opt-in shape `backend.prod.Dockerfile`
            # already uses for a different optional, heavy dependency.
            from sentence_transformers import CrossEncoder

            logger.info(
                "Loading cross-encoder reranker model '%s'...", self._model_name
            )
            self._model = CrossEncoder(self._model_name)
        return self._model

    async def rerank(
        self, query: str, documents: list[Document], *, top_k: int
    ) -> list[Document]:
        if not documents:
            return []

        try:
            model = await asyncio.to_thread(self._load)
            pairs = [(query, document.page_content) for document in documents]
            scores = await asyncio.to_thread(model.predict, pairs)
        except Exception:
            logger.exception(
                "Cross-encoder reranking failed; falling back to the "
                "fused (pre-rerank) order."
            )
            return documents[:top_k]

        ranked = sorted(
            zip(documents, scores), key=lambda item: item[1], reverse=True
        )
        return [document for document, _ in ranked[:top_k]]
