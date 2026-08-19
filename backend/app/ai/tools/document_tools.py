"""Tool factories the assistant agent can bind for one turn.

Every handler here is a closure over the document already attached to *this*
request (``document_id``, ``cached_document``) -- the model is never given a
document id to pass as an argument, so it structurally cannot search or read
any document other than the one the user actually attached. When no document
is attached, :func:`build_assistant_tools` simply omits the document-scoped
tools; the model never sees them to call in the first place.
"""

import json
import logging
from typing import Any, Callable, Optional

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.ai.documents.anchors import format_anchor
from app.ai.documents.outline import build_outline, format_outline
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.guardrails.sensitivity import assessment_from_analysis
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.tools.mevzuat_tools import build_live_legislation_tools
from app.ai.tools.registry import ToolSpec
from app.ai.workflows.events import child_config
from app.core.enums.sensitivity_level import SensitivityLevel
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

QA_COLLECTION_NAME = "document_qa"

#: Fallback slice size when vector search returns nothing at all and there is
#: no other way to answer. Bounded so it doesn't blow the prompt budget.
TEXT_SLICE_CHARS = 8000


class ToolResult(BaseModel):
    """What a tool actually returned, for the output gate rather than the model.

    The model only ever sees the plain string a handler returns (LangChain's
    tool-call contract needs a string, and changing that is out of scope
    here) -- this is a parallel, structured record of the same call, reported
    through ``on_tool_result`` the same way ``on_anchor_referenced`` already
    reports page references. ``app.ai.guardrails.output_gate.evaluate_response``
    uses ``text``/``source_ids`` as this turn's groundedness sources and
    ``sensitivity_level`` to know whether a leaked PII span traces back to a
    confidentiality-marked document.
    """

    tool: str = Field(description="The tool name that produced this result.")
    text: str = Field(description="The same text returned to the model.")
    citations: list[str] = Field(
        default_factory=list, description="Page anchors referenced (e.g. '[s. 3]')."
    )
    source_ids: list[str] = Field(
        default_factory=list, description="Document/legislation identifiers this result drew on."
    )
    sensitivity_level: SensitivityLevel = Field(default=SensitivityLevel.UNMARKED)
    confidence: float = Field(
        default=1.0, description="1.0 for a real retrieval hit, lower for a degraded fallback path."
    )


class SearchDocumentArgs(BaseModel):
    """Arguments for the ``search_document`` tool."""

    query: str = Field(description="Belgede aranacak soru veya anahtar kelimeler.")


class GetDocumentDetailsArgs(BaseModel):
    """``get_document_details`` takes no arguments; analysis is already scoped
    to the one attached document."""


class GetDocumentOutlineArgs(BaseModel):
    """``get_document_outline`` takes no arguments; it lists every page of
    the one attached document."""


class GetDocumentSectionArgs(BaseModel):
    """Arguments for the ``get_document_section`` tool."""

    page: int = Field(description="Okunacak sayfa numarası (1'den başlar).")


class SearchLegislationArgs(BaseModel):
    """Arguments for the ``search_legislation`` tool."""

    query: str = Field(description="Mevzuat veritabanında aranacak konu veya soru.")


#: Returned by every document-scoped tool instead of the real passage when
#: the requester's clearance doesn't cover the document's confidentiality
#: level -- deny-at-retrieval, the cheapest and most robust point to stop a
#: leak (the content never reaches the model's context at all, so it can't
#: be paraphrased around ``output_gate.py``'s downstream checks).
_CLEARANCE_REFUSAL = "Bu belgenin içeriğini görüntülemek için yeterli yetkiniz yok."


def build_assistant_tools(
    *,
    document_id: Optional[str],
    cached_document: dict[str, Any],
    vector_store: Optional[BaseVectorStore],
    embeddings_client: Optional[BaseEmbeddingsClient],
    qa_sparse_encoder: SparseBM25Encoder,
    qa_result_limit: int,
    rag_graph: Any,
    config: Optional[RunnableConfig],
    on_anchor_referenced: Optional[Callable[[str], None]] = None,
    on_tool_result: Optional[Callable[[ToolResult], None]] = None,
    requester_clearance: Optional[SensitivityLevel] = None,
) -> list[ToolSpec]:
    """Build the tool set available to the assistant agent for one turn.

    Args:
        document_id: Storage path of the attached document, or None.
        cached_document: The document's cached analysis/extracted text/pages,
            when ``document_id`` is set (see
            ``planning_graph._load_cached_document``).
        vector_store: Vector store backing document retrieval.
        embeddings_client: Embeddings client backing document retrieval.
        qa_sparse_encoder: Unfit sparse encoder, same one the pre-merge
            document Q&A path used for RRF fusion's lexical half.
        qa_result_limit: Max passages a document search returns.
        rag_graph: Compiled legislation retrieval sub-graph.
        config: The assist step's runnable config, forwarded to the RAG
            sub-graph via ``child_config`` so its own progress events (and any
            tracing callbacks) still reach the SSE stream.
        on_anchor_referenced: Called with a page anchor (e.g. ``"[s. 3]"``)
            whenever ``get_document_section`` reads a page, so the caller can
            carry it into ``SessionFocus.last_referenced_anchor``.
        on_tool_result: Called with a ``ToolResult`` after every tool call
            that returns real content, so the caller can accumulate this
            turn's actual sources for ``output_gate.evaluate_response`` to
            check groundedness/leakage against -- see ``ToolResult``'s
            docstring for why this is a side-channel rather than a change to
            what handlers return to the model.
        requester_clearance: The authenticated caller's resolved clearance
            (see ``app.core.permissions.role_checker.clearance_for``).
            ``None`` skips the check entirely -- same convention
            ``chat/router.py``'s ownership check already uses for "no
            authenticated user" (``settings.REQUIRE_AUTH`` off), so the
            documented local-dev escape hatch stays genuinely open rather
            than silently refusing every document tool call. This is
            narrower than ``output_gate.py``'s own ``requester_clearance``
            handling, which stays fail-secure on ``None`` for the rarer
            PII/semantic-leak block -- deny-at-retrieval here is a coarser,
            much more frequently hit gate, and the two are independent
            layers of the same defense, not required to agree on every edge.

    Returns:
        Document-scoped tools only when a document is attached; legislation
        search whenever a RAG graph is available, document or not.
    """
    tools: list[ToolSpec] = []

    def _report(result: ToolResult) -> None:
        if on_tool_result:
            on_tool_result(result)

    if document_id:
        document_sensitivity = assessment_from_analysis(
            cached_document.get("analysis") or {}
        ).effective_level
        clearance_ok = (
            requester_clearance is None or requester_clearance >= document_sensitivity
        )

        def _pages() -> list[str]:
            pages = cached_document.get("pages")
            if pages:
                return pages
            text = cached_document.get("extracted_text")
            return [text] if text else []

        async def _search_document(query: str) -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            if not (vector_store and embeddings_client):
                return "Belge arama şu anda kullanılamıyor."
            passages: list[str] = []
            try:
                query_vector = await embeddings_client.embed_query(query)
                sparse_indices, sparse_values = qa_sparse_encoder.encode_query(query)
                # Defense-in-depth alongside the clearance_ok gate above: every
                # chunk of this document was tagged with the same
                # document-level rank (see DocumentService._index_for_qa), so
                # this is currently redundant with that whole-document check
                # for this single-document-scoped tool -- but it costs
                # nothing here and is what actually protects a future
                # cross-document search tool from ever letting Qdrant return
                # an over-classified chunk in the first place.
                search_filter: dict[str, Any] = {"storage_path": document_id}
                if requester_clearance is not None:
                    search_filter["sensitivity_rank"] = {"lte": requester_clearance.rank}
                hits = await vector_store.hybrid_search(
                    collection_name=QA_COLLECTION_NAME,
                    query_vector=query_vector,
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    limit=qa_result_limit,
                    filter_dict=search_filter,
                )
                for hit in hits:
                    text = hit.get("text")
                    if not text:
                        continue
                    page = (hit.get("metadata") or {}).get("page")
                    passages.append(f"{format_anchor(page)} {text}" if page else text)
            except Exception:
                logger.exception("Assistant document search failed")

            confidence = 1.0
            degraded = False
            if not passages and cached_document.get("extracted_text"):
                # A retrieval outage and "genuinely no matching passage" used
                # to collapse into this same branch with no distinguishing
                # signal, so the model read the document's opening lines with
                # the same confidence as a real targeted hit -- and a
                # question about page 40 of a 60-page document got answered,
                # wrongly, from pages 1-2. `confidence` already recorded the
                # difference for ToolResult/output_gate's groundedness check;
                # `degraded` carries the same fact into the text the model
                # itself reads, which previously had no marker at all.
                passages = [cached_document["extracted_text"][:TEXT_SLICE_CHARS]]
                confidence = 0.5
                degraded = True
            if not passages:
                return "Belgede bu soruyla ilgili bir içerik bulunamadı."

            text = "\n\n---\n\n".join(passages)
            if degraded:
                text = (
                    "[Not: Hedefli arama sonuç vermedi; bu, belgenin yalnızca "
                    "başlangıç kısmıdır ve sorunuzla doğrudan ilgili olmayabilir.]"
                    f"\n\n{text}"
                )
            _report(
                ToolResult(
                    tool="search_document",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                    confidence=confidence,
                )
            )
            return text

        async def _get_document_details() -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            analysis = cached_document.get("analysis") or {}
            if not analysis:
                return "Belge analiz bilgisi mevcut değil."

            raw_metadata = analysis.get("fields") or analysis.get("metadata") or {}
            metadata = (
                json.dumps(raw_metadata, ensure_ascii=False, indent=2, default=str)
                if isinstance(raw_metadata, dict)
                else str(raw_metadata)
            )
            parts = [
                f"Özet: {analysis.get('summary') or 'Özet mevcut değil.'}",
                f"Üst veri: {metadata}",
            ]
            if analysis.get("compliance_status"):
                parts.append(f"Uygunluk durumu: {analysis['compliance_status']}")
            if analysis.get("missing_fields"):
                # Every producer of this list writes MissingField.model_dump()
                # dicts (see document_analysis_graph.py's check_compliance_node),
                # never bare strings -- joining the list directly raised
                # TypeError on any document with a real compliance gap, which
                # the assistant then swallowed and answered without the
                # document's analysis at all, silently. `label` is the one key
                # every dict is guaranteed to carry.
                labels = [
                    item.get("label", str(item)) if isinstance(item, dict) else str(item)
                    for item in analysis["missing_fields"]
                ]
                parts.append("Eksik alanlar: " + ", ".join(labels))
            text = "\n\n".join(parts)
            _report(
                ToolResult(
                    tool="get_document_details",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        async def _get_document_outline() -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            text = format_outline(build_outline(pages))
            _report(
                ToolResult(
                    tool="get_document_outline",
                    text=text,
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        async def _get_document_section(page: int) -> str:
            if not clearance_ok:
                return _CLEARANCE_REFUSAL
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            if page < 1 or page > len(pages):
                return f"Belgede {page}. sayfa yok. Belge {len(pages)} sayfadan oluşuyor."
            anchor = format_anchor(page)
            if on_anchor_referenced:
                on_anchor_referenced(anchor)
            text = f"{anchor}\n\n{pages[page - 1]}"
            _report(
                ToolResult(
                    tool="get_document_section",
                    text=text,
                    citations=[anchor],
                    source_ids=[document_id],
                    sensitivity_level=document_sensitivity,
                )
            )
            return text

        tools.extend(
            [
                ToolSpec(
                    name="search_document",
                    description=(
                        "Yüklenmiş belgede belirli bir soru veya konuyla ilgili "
                        "içerik ara. Belgenin belirli bir kısmı hakkında soru "
                        "sorulduğunda kullan. Sonuçlar [s. N] ile sayfa atfı taşır."
                    ),
                    args_schema=SearchDocumentArgs,
                    handler=_search_document,
                ),
                ToolSpec(
                    name="get_document_details",
                    description=(
                        "Belgenin özetini, üst verilerini (tarih, sayı, konu, "
                        "muhatap vb.) ve uygunluk denetimi sonucunu getirir. "
                        "Belgenin genel niteliği hakkında soru sorulduğunda kullan."
                    ),
                    args_schema=GetDocumentDetailsArgs,
                    handler=_get_document_details,
                ),
                ToolSpec(
                    name="get_document_outline",
                    description=(
                        "Belgenin sayfa listesini ve her sayfanın ilk satırını "
                        "getirir. Belgenin genel yapısını görmek veya hangi "
                        "sayfada ne olduğunu bulmak için search_document sonuç "
                        "vermeden önce ya da 'kaç sayfa' gibi sorularda kullan."
                    ),
                    args_schema=GetDocumentOutlineArgs,
                    handler=_get_document_outline,
                ),
                ToolSpec(
                    name="get_document_section",
                    description=(
                        "Belgenin belirli bir sayfasının tam metnini okur. "
                        "Kullanıcı belirli bir sayfayı işaret ettiğinde (örn. "
                        "'3. sayfayı açıkla') veya get_document_outline ile "
                        "ilgili sayfayı belirledikten sonra kullan."
                    ),
                    args_schema=GetDocumentSectionArgs,
                    handler=_get_document_section,
                ),
            ]
        )

    if rag_graph is not None:

        async def _search_legislation(query: str) -> str:
            try:
                result = await rag_graph.ainvoke(
                    {"original_query": query, "attempts": 0},
                    config=child_config(config),
                )
                context = result.get("context") or ""
            except Exception:
                logger.exception("Assistant legislation search failed")
                context = ""
            if not context:
                return "İlgili bir mevzuat maddesi bulunamadı."
            # Legislation is public reference material by nature, never a
            # confidentiality-marked source -- always UNMARKED regardless of
            # whether a document happens to be attached this turn.
            _report(ToolResult(tool="search_legislation", text=context))
            return context

        tools.append(
            ToolSpec(
                name="search_legislation",
                description=(
                    "İlgili kanun, yönetmelik ve mevzuat maddelerini ara. "
                    "Kullanıcı mevzuat veya hukuki dayanak hakkında soru "
                    "sorduğunda kullan."
                ),
                args_schema=SearchLegislationArgs,
                handler=_search_legislation,
            )
        )

    # Appended after the corpus tool on purpose: the model picks from an ordered
    # list, and the offline path should be the default. This adds nothing when
    # MEVZUAT_MCP_ENABLED is off, so the model is never offered a tool that
    # cannot run.
    tools.extend(build_live_legislation_tools())

    return tools
