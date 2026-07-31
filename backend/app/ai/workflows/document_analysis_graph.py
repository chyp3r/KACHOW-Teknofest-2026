import logging
from copy import deepcopy
from typing import Any, Optional, TypedDict

from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, create_model

from app.ai.agents.classifier import ClassifierAgent
from app.ai.agents.compliance import ComplianceAgent
from app.ai.compliance import (
    DOCUMENT_TYPE_LABELS,
    EvrakField,
    check_required_fields,
    detect_structural_signal,
    format_parsed_fields,
    format_structural_signal,
    merge_parsed_over_model,
    parse_labelled_fields,
)
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.events import emit_node_end, emit_node_start, emit_partial
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

logger = logging.getLogger(__name__)

#: Header fields sit on the first page and the imza/ek block at the very end;
#: the middle body matters for the summary, not for field extraction.
HEAD_CHAR_BUDGET = 6000
TAIL_CHAR_BUDGET = 1500
MEVZUAT_RESULT_LIMIT = 3

#: The merged classify+extract call emits a nested object with a dozen fields.
ANALYSIS_MAX_TOKENS = 1536


class DocumentAnalysisState(TypedDict, total=False):
    """LangGraph state for the incoming-document (evrak) analysis workflow."""

    input_text: str
    is_ocr_text: bool
    document_type: str
    document_type_label: str
    summary: str
    fields: dict[str, Any]
    missing_fields: list[dict[str, Any]]
    compliance_status: str
    checked_field_count: int
    mevzuat_documents: list[Document]
    mevzuat_suggestions: list[dict[str, Any]]
    entities: list[str]


#: Type and summary only. Used as the fallback when the merged schema fails.
class DocumentClassificationOutput(BaseModel):
    """Structured type and summary of an incoming official document."""

    document_type: DocumentType = Field(
        description=(
            "Gelen evrakın türü. Yalnızca şu değerlerden biri olmalıdır: "
            "official_letter (resmî yazı), petition (dilekçe), "
            "information_request (bilgi edinme başvurusu), complaint (şikayet), "
            "circular (genelge), directive (talimat), report (rapor), "
            "minutes (tutanak), leave_request (izin talebi), other (diğer)."
        )
    )
    summary: str = Field(
        description="Evrakın kısa, öz ve nesnel Türkçe özeti (en çok 3 cümle)."
    )


def _build_merged_output_model() -> type[BaseModel]:
    """Build the combined analysis schema as a *flat* model.

    Classification and field extraction used to be two model calls over the same
    text, reading the same evidence, so the second re-ingested a prompt the first
    had already paid for. Merging them halves the analysis leg.

    The merge is generated from :class:`EvrakField` rather than hand-written, and
    deliberately flattened rather than nesting ``fields: EvrakField``. Local 9B
    models emit malformed JSON for nested object schemas often enough that the
    nested version failed validation on both attempts and fell through to the
    "Evrak özeti çıkarılamadı." path. A flat schema of scalars and string lists
    is what they reliably produce -- and generating it from ``EvrakField`` keeps
    a single source of truth for the field definitions.

    Returns:
        A Pydantic model with ``document_type``, ``summary`` and every
        ``EvrakField`` attribute at the top level.
    """
    definitions: dict[str, Any] = {
        "document_type": (
            DocumentType,
            Field(
                description=(
                    "Gelen evrakın türü. Yalnızca şu değerlerden biri olmalıdır: "
                    "official_letter, petition, information_request, complaint, "
                    "circular, directive, report, minutes, leave_request, other."
                )
            ),
        ),
        "summary": (
            str,
            Field(description="Evrakın kısa, öz ve nesnel Türkçe özeti (en çok 3 cümle)."),
        ),
    }
    for name, info in EvrakField.model_fields.items():
        # Deep-copied: FieldInfo instances carry per-model state, and handing
        # EvrakField's own objects to a second model would have the two share it.
        definitions[name] = (info.annotation, deepcopy(info))

    return create_model("MergedDocumentAnalysisOutput", **definitions)


DocumentAnalysisOutput = _build_merged_output_model()

#: Keys belonging to EvrakField, used to split the flat model back apart.
EVRAK_FIELD_KEYS = tuple(EvrakField.model_fields)


class MevzuatSuggestion(BaseModel):
    """A single legislation reference relevant to the document."""

    mevzuat: str = Field(
        description="İlgili mevzuatın adı ve varsa madde numarası, alıntıda yazıldığı biçimde."
    )
    aciklama: str = Field(
        description="Bu hükmün evrakla ilişkisini açıklayan kısa Türkçe gerekçe."
    )


class MevzuatSuggestionOutput(BaseModel):
    """Structured legislation suggestions grounded in retrieved excerpts."""

    suggestions: list[MevzuatSuggestion] = Field(
        default_factory=list,
        description="Yalnızca verilen alıntılara dayanan mevzuat önerileri.",
    )


def _trim_for_extraction(text: str) -> str:
    """Shorten a document so its header and signature block survive truncation.

    Args:
        text: Full document text.

    Returns:
        The text unchanged when short enough, otherwise head and tail joined by
        an explicit elision marker.
    """
    if len(text) <= HEAD_CHAR_BUDGET + TAIL_CHAR_BUDGET:
        return text
    return (
        f"{text[:HEAD_CHAR_BUDGET]}"
        "\n\n[... belgenin orta kısmı kısaltıldı ...]\n\n"
        f"{text[-TAIL_CHAR_BUDGET:]}"
    )


def _ocr_warning(is_ocr_text: bool) -> str:
    """Return a prompt note when the text came from OCR.

    Args:
        is_ocr_text: Whether the source text was produced by OCR.

    Returns:
        A Turkish caution string, or an empty string.
    """
    if not is_ocr_text:
        return ""
    return (
        "\n\nUYARI: Bu metin taranmış bir belgeden OCR ile okunmuştur; harf "
        "hataları olabilir. Emin olmadığın alanları uydurmak yerine null bırak."
    )


def _build_mevzuat_query(state: DocumentAnalysisState) -> str:
    """Compose the legislation search query deterministically.

    Built from the document-type label and the subject rather than from a model
    rewrite: those labels are literal tokens in the regulation, which is what the
    BM25 half of the hybrid retriever matches best.

    Deliberately does not depend on the compliance report, so retrieval and
    compliance checking can run as independent branches.

    Args:
        state: Current workflow state.

    Returns:
        The search query.
    """
    parts = [state.get("document_type_label") or "resmî yazı"]

    fields = state.get("fields") or {}
    konu = fields.get("konu")
    if konu:
        parts.append(str(konu))

    parts.append("zorunlu unsurlar sayı tarih konu ilgi imza gizlilik derecesi")
    return " ".join(parts).strip()


def create_document_analysis_graph(
    llm_client: BaseLLMClient,
    mevzuat_retriever: Optional[HybridRetriever] = None,
    reasoning_llm_client: Optional[BaseLLMClient] = None,
):
    """Create and compile the incoming-document analysis workflow.

    Flow::

        START -> analyze -+-> check_compliance -+-> suggest_mevzuat -> END
                          \\-> retrieve_mevzuat -/

    Compliance checking is pure computation and legislation retrieval is network
    I/O, so they run as concurrent branches. They write disjoint state keys,
    which is what makes the fan-out safe without custom reducers.

    Args:
        llm_client: The LLM used for document analysis.
        mevzuat_retriever: Optional legislation retriever. When omitted, the two
            legislation nodes degrade to no-ops and the rest still runs.
        reasoning_llm_client: Optional separate client for the legislation
            suggestion step. Defaults to ``llm_client``.

    Returns:
        The compiled LangGraph workflow.
    """
    classifier_agent = ClassifierAgent(llm_client)
    compliance_agent = ComplianceAgent(reasoning_llm_client or llm_client)

    async def analyze_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Classify the document and extract its header fields in one call."""
        logger.info("Running Document Analysis Node (classify + extract)...")
        await emit_node_start(
            config,
            "classification",
            "Evrak Analizi",
            "Belge sınıflandırılıyor ve üst veriler çıkarılıyor...",
        )

        text = _trim_for_extraction(state["input_text"])

        # The regulation prescribes the header layout, so labelled fields are
        # read with regular expressions rather than by the model. The parser
        # scores 60/60 on the sample corpus with no invented values.
        parsed = parse_labelled_fields(text)
        logger.info("Parsed %d labelled field(s) deterministically.", len(parsed))

        prompt = (
            "Aşağıdaki evrakın türünü belirle, kısa bir özetini çıkar ve üstveri "
            "alanlarını doldur.\n\n"
            "Tür ayrımında şu ölçütleri kullan:\n"
            "- official_letter: 'T.C.' başlığı, kurum antedi, Sayı/Tarih/Konu "
            "alanları ve kurum yetkilisinin unvanlı imzası bulunan yazı. "
            "Kurumlar arası yazışmaların varsayılan türüdür.\n"
            "- petition: bir vatandaşın kendi adına talep veya şikayet ilettiği, "
            "kurum antedi bulunmayan başvuru.\n"
            "- information_request: yalnızca 4982 sayılı Kanun kapsamında bilgi "
            "veya belge talebi açıkça istendiğinde.\n"
            "- complaint: şikayet bildirimi. circular: genelge. "
            "directive: talimat. report: rapor. minutes: tutanak.\n"
            "- leave_request: izin talebi.\n"
            "- other: yalnızca yukarıdakilerin hiçbiri uymuyorsa.\n\n"
            "Kurum antetli ve unvanlı imza taşıyan bir yazıyı vatandaş başvurusu "
            "olarak sınıflandırma.\n"
            "Alan çıkarımında belgede gerçekten bulunmayan alanları null bırak; "
            "tahmin etme, örnek değer üretme.\n\n"
            f'EVRAK:\n"""\n{text}\n"""'
            # Deterministic regex observations, injected as facts rather than as
            # instructions. Measured on qwen3:8b these cut the harmful
            # official_letter -> petition confusion, which matters because the
            # document type selects the required-field rule table.
            f"{format_structural_signal(detect_structural_signal(state['input_text']))}"
            f"{format_parsed_fields(parsed)}"
            f"{_ocr_warning(state.get('is_ocr_text', False))}"
        )

        try:
            res = await classifier_agent.run_structured(
                messages=prompt,
                response_model=DocumentAnalysisOutput,
                temperature=0.0,
                max_tokens=ANALYSIS_MAX_TOKENS,
            )
            payload = res.model_dump()
            document_type = DocumentType(payload["document_type"])
            summary = payload["summary"]
            model_fields = {key: payload.get(key) for key in EVRAK_FIELD_KEYS}
        except Exception:
            # Fall back to type and summary alone. The merged schema is the
            # fast path, not a requirement: a smaller model that cannot hold the
            # full field list should still produce a usable classification
            # rather than dropping the document to "other".
            logger.warning(
                "Merged analysis failed; retrying with classification only.",
                exc_info=True,
            )
            try:
                fallback: DocumentClassificationOutput = (
                    await classifier_agent.run_structured(
                        messages=prompt,
                        response_model=DocumentClassificationOutput,
                        temperature=0.0,
                        max_retries=1,
                    )
                )
                document_type = DocumentType(fallback.document_type)
                summary = fallback.summary
            except Exception:
                logger.exception("Document Analysis Node failed")
                document_type = DocumentType.OTHER
                summary = "Evrak özeti çıkarılamadı."
            # The deterministically parsed fields still stand: a model failure
            # must not discard values read straight off the document.
            model_fields = EvrakField().model_dump()

        merged_fields = merge_parsed_over_model(model_fields, parsed)
        update = {
            "document_type": document_type.value,
            "document_type_label": DOCUMENT_TYPE_LABELS[document_type],
            "summary": summary,
            "fields": merged_fields,
            "entities": merged_fields.get("entities", []),
        }

        # Surface the classification immediately. The draft is what dominates
        # wall-clock time, and there is no reason for the user to stare at a
        # spinner while results that already exist are withheld.
        await emit_partial(config, "classification", update)
        return update

    async def check_compliance_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Check required fields. Pure set subtraction; no LLM involved."""
        logger.info("Running Compliance Check Node...")
        try:
            fields = EvrakField(**(state.get("fields") or {}))
            report = check_required_fields(
                state.get("document_type", DocumentType.OTHER.value), fields
            )
            update = {
                "missing_fields": [item.model_dump() for item in report.missing_fields],
                "compliance_status": report.status.value,
                "checked_field_count": report.checked_field_count,
            }
        except Exception:
            logger.exception("Compliance Check Node failed")
            update = {
                "missing_fields": [],
                "compliance_status": ComplianceStatus.INCOMPLETE.value,
                "checked_field_count": 0,
            }

        await emit_partial(config, "compliance", update)
        return update

    async def retrieve_mevzuat_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Retrieve legislation excerpts for the document."""
        if mevzuat_retriever is None:
            logger.info("No mevzuat retriever configured; skipping retrieval.")
            return {"mevzuat_documents": []}

        logger.info("Running Mevzuat Retrieval Node...")
        try:
            documents = await mevzuat_retriever.retrieve(
                _build_mevzuat_query(state), limit=MEVZUAT_RESULT_LIMIT
            )
            logger.info("Retrieved %d mevzuat excerpt(s).", len(documents))
            return {"mevzuat_documents": documents}
        except Exception:
            logger.exception("Mevzuat Retrieval Node failed")
            return {"mevzuat_documents": []}

    async def suggest_mevzuat_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Explain how the retrieved provisions bear on this document."""
        documents = state.get("mevzuat_documents") or []
        if not documents:
            logger.info("No mevzuat excerpts available; skipping suggestion.")
            await emit_node_end(
                config, "classification", "Evrak Analizi", "Evrak analizi tamamlandı."
            )
            return {"mevzuat_suggestions": []}

        logger.info("Running Mevzuat Suggestion Node...")
        excerpts = "\n\n".join(
            f"[ALINTI {index}] (Kaynak: {document.metadata.get('mevzuat', 'bilinmiyor')})\n"
            f"{document.page_content}"
            for index, document in enumerate(documents, start=1)
        )
        missing_labels = ", ".join(
            item.get("label", "") for item in state.get("missing_fields") or []
        )
        prompt = (
            f"Evrak türü: {state.get('document_type_label', 'bilinmiyor')}\n"
            f"Evrak özeti: {state.get('summary', '')}\n"
            f"Tespit edilen eksik alanlar: {missing_labels or 'yok'}\n\n"
            f'MEVZUAT ALINTILARI:\n"""\n{excerpts}\n"""\n\n'
            "Yalnızca yukarıdaki alıntılara dayanarak bu evrakla ilgili mevzuat "
            "hükümlerini listele. Alıntılarda bulunmayan madde numarası veya kanun "
            "adı üretme."
        )
        try:
            res: MevzuatSuggestionOutput = await compliance_agent.run_structured(
                messages=prompt,
                response_model=MevzuatSuggestionOutput,
                temperature=0.0,
            )
            suggestions = [item.model_dump() for item in res.suggestions]
        except Exception:
            logger.exception("Mevzuat Suggestion Node failed")
            # Degrade to the raw citations rather than losing the requirement.
            suggestions = [
                {
                    "mevzuat": document.metadata.get("mevzuat", "Bilinmeyen kaynak"),
                    "aciklama": "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi).",
                }
                for document in documents
            ]

        await emit_node_end(
            config,
            "classification",
            "Evrak Analizi",
            "Evrak analizi tamamlandı.",
            {"mevzuat_suggestions": suggestions},
        )
        return {"mevzuat_suggestions": suggestions}

    builder = StateGraph(DocumentAnalysisState)
    builder.add_node("analyze", analyze_node)
    builder.add_node("check_compliance", check_compliance_node)
    builder.add_node("retrieve_mevzuat", retrieve_mevzuat_node)
    builder.add_node("suggest_mevzuat", suggest_mevzuat_node)

    builder.add_edge(START, "analyze")
    # Fan out: compliance is CPU-bound, retrieval is network-bound.
    builder.add_edge("analyze", "check_compliance")
    builder.add_edge("analyze", "retrieve_mevzuat")
    # Fan in: LangGraph waits for both branches before running this node.
    builder.add_edge("check_compliance", "suggest_mevzuat")
    builder.add_edge("retrieve_mevzuat", "suggest_mevzuat")
    builder.add_edge("suggest_mevzuat", END)

    return builder.compile()
