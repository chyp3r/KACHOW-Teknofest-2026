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
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.tools.registry import ToolSpec
from app.ai.workflows.events import child_config
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)

QA_COLLECTION_NAME = "document_qa"

#: Fallback slice size when vector search returns nothing at all and there is
#: no other way to answer. Bounded so it doesn't blow the prompt budget.
TEXT_SLICE_CHARS = 8000


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

    Returns:
        Document-scoped tools only when a document is attached; legislation
        search whenever a RAG graph is available, document or not.
    """
    tools: list[ToolSpec] = []

    if document_id:

        def _pages() -> list[str]:
            pages = cached_document.get("pages")
            if pages:
                return pages
            text = cached_document.get("extracted_text")
            return [text] if text else []

        async def _search_document(query: str) -> str:
            if not (vector_store and embeddings_client):
                return "Belge arama şu anda kullanılamıyor."
            passages: list[str] = []
            try:
                query_vector = await embeddings_client.embed_query(query)
                sparse_indices, sparse_values = qa_sparse_encoder.encode_query(query)
                hits = await vector_store.hybrid_search(
                    collection_name=QA_COLLECTION_NAME,
                    query_vector=query_vector,
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    limit=qa_result_limit,
                    filter_dict={"storage_path": document_id},
                )
                for hit in hits:
                    text = hit.get("text")
                    if not text:
                        continue
                    page = (hit.get("metadata") or {}).get("page")
                    passages.append(f"{format_anchor(page)} {text}" if page else text)
            except Exception:
                logger.exception("Assistant document search failed")

            if not passages and cached_document.get("extracted_text"):
                passages = [cached_document["extracted_text"][:TEXT_SLICE_CHARS]]
            if not passages:
                return "Belgede bu soruyla ilgili bir içerik bulunamadı."
            return "\n\n---\n\n".join(passages)

        async def _get_document_details() -> str:
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
                parts.append(
                    "Eksik alanlar: " + ", ".join(analysis["missing_fields"])
                )
            return "\n\n".join(parts)

        async def _get_document_outline() -> str:
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            return format_outline(build_outline(pages))

        async def _get_document_section(page: int) -> str:
            pages = _pages()
            if not pages:
                return "Belge metni mevcut değil."
            if page < 1 or page > len(pages):
                return f"Belgede {page}. sayfa yok. Belge {len(pages)} sayfadan oluşuyor."
            anchor = format_anchor(page)
            if on_anchor_referenced:
                on_anchor_referenced(anchor)
            return f"{anchor}\n\n{pages[page - 1]}"

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
            return context or "İlgili bir mevzuat maddesi bulunamadı."

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

    return tools
