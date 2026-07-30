import logging
from typing import Any, Optional, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.classifier import ClassifierAgent
from app.ai.agents.compliance import ComplianceAgent
from app.ai.agents.metadata import MetadataAgent
from app.ai.compliance import (
    DOCUMENT_TYPE_LABELS,
    EvrakField,
    check_required_fields,
)
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

logger = logging.getLogger(__name__)

#: Ollama's default context window silently truncates long documents from the
#: beginning -- exactly where sayı, tarih, konu and muhatap live. Ask for a larger
#: window and additionally trim the middle, which the field extractor never needs.
EXTRACTION_NUM_CTX = 8192
HEAD_CHAR_BUDGET = 6000
TAIL_CHAR_BUDGET = 1500
MEVZUAT_RESULT_LIMIT = 5


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

    Header fields sit on the first page and the imza/ek block at the very end;
    the middle body matters for the summary, not for field extraction.

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

    Built from the document-type label, the subject and the Turkish labels of the
    missing fields rather than from a model rewrite: those labels ("sayı", "ilgi",
    "gizlilik derecesi") are literal tokens in the regulation, which is what the
    BM25 half of the hybrid retriever matches best.

    Args:
        state: Current workflow state.

    Returns:
        The search query.
    """
    parts = [state.get("document_type_label") or "resmî yazı"]

    konu = (state.get("fields") or {}).get("konu")
    if konu:
        parts.append(str(konu))

    missing_labels = [
        item.get("label", "")
        for item in state.get("missing_fields") or []
        if item.get("label")
    ]
    if missing_labels:
        parts.append("zorunlu unsurlar: " + ", ".join(missing_labels))

    return " ".join(parts).strip()


def create_document_analysis_graph(
    llm_client: BaseLLMClient,
    mevzuat_retriever: Optional[HybridRetriever] = None,
):
    """Create and compile the incoming-document analysis workflow.

    Flow: START -> Classify -> Extract Fields -> Check Compliance
          -> Retrieve Legislation -> Suggest Legislation -> END

    Deliberately a sibling of `classification_graph` rather than an extension of
    it: that graph is invoked by `planning_graph` on every chat turn and reads only
    `summary`, so wiring a retriever and two extra model calls into it would tax
    the chat path for a value nobody reads. It also classifies into free-text
    Turkish, which cannot key the required-field rule table.

    Args:
        llm_client: The LLM provider used by every agent in the graph.
        mevzuat_retriever: Optional legislation retriever. When omitted, the two
            legislation nodes degrade to no-ops and the rest of the analysis still
            runs.

    Returns:
        The compiled LangGraph workflow.
    """
    classifier_agent = ClassifierAgent(llm_client)
    metadata_agent = MetadataAgent(llm_client)
    compliance_agent = ComplianceAgent(llm_client)

    # 1. Classification Node
    async def classify_node(state: DocumentAnalysisState) -> dict[str, Any]:
        logger.info("Running Document Classification Node...")
        prompt = (
            "Aşağıdaki evrakın türünü belirle ve kısa bir özetini çıkar.\n\n"
            "Tür ayrımında şu ölçütleri kullan:\n"
            "- official_letter: 'T.C.' başlığı, kurum antedi, Sayı/Tarih/Konu "
            "alanları ve kurum yetkilisinin unvanlı imzası bulunan, bir kurumdan "
            "gönderilen yazı. Kurumlar arası yazışmaların varsayılan türüdür.\n"
            "- petition: bir vatandaşın kendi adına talep veya şikayet ilettiği, "
            "kurum antedi bulunmayan başvuru.\n"
            "- information_request: yalnızca 4982 sayılı Kanun kapsamında bilgi "
            "veya belge talebi açıkça istendiğinde kullanılır.\n"
            "- complaint: şikayet bildirimi. circular: genelge. "
            "directive: talimat. report: rapor. minutes: tutanak.\n"
            "- leave_request: izin talebi.\n"
            "- other: yalnızca yukarıdakilerin hiçbiri uymuyorsa.\n\n"
            "Kurum antetli ve unvanlı imza taşıyan bir yazıyı vatandaş başvurusu "
            "olarak sınıflandırma.\n\n"
            f"EVRAK:\n\"\"\"\n{_trim_for_extraction(state['input_text'])}\n\"\"\""
            f"{_ocr_warning(state.get('is_ocr_text', False))}"
        )
        try:
            res: DocumentClassificationOutput = await classifier_agent.run_structured(
                messages=prompt,
                response_model=DocumentClassificationOutput,
                temperature=0.0,
            )
            document_type = DocumentType(res.document_type)
            return {
                "document_type": document_type.value,
                "document_type_label": DOCUMENT_TYPE_LABELS[document_type],
                "summary": res.summary,
            }
        except Exception:
            logger.exception("Document Classification Node failed")
            return {
                "document_type": DocumentType.OTHER.value,
                "document_type_label": DOCUMENT_TYPE_LABELS[DocumentType.OTHER],
                "summary": "Evrak özeti çıkarılamadı.",
            }

    # 2. Field Extraction Node
    async def extract_field_node(state: DocumentAnalysisState) -> dict[str, Any]:
        logger.info("Running Evrak Field Extraction Node...")
        # Kept deliberately short. A longer version enumerating field positions and
        # prohibitions was measured against qwen3:8b and made it return an empty
        # object on every run, while this wording extracts tarih and konu reliably.
        # Field placement guidance belongs in the schema descriptions, not here.
        prompt = (
            "Aşağıdaki resmî evraktan üstveri alanlarını çıkar. Bir alan belgede "
            "gerçekten yoksa o alanı null bırak; tahmin etme, örnek değer üretme.\n\n"
            f"EVRAK:\n\"\"\"\n{_trim_for_extraction(state['input_text'])}\n\"\"\""
            f"{_ocr_warning(state.get('is_ocr_text', False))}"
        )
        try:
            res: EvrakField = await metadata_agent.run_structured(
                messages=prompt,
                response_model=EvrakField,
                temperature=0.0,
                num_ctx=EXTRACTION_NUM_CTX,
            )
            return {"fields": res.model_dump()}
        except Exception:
            logger.exception("Evrak Field Extraction Node failed")
            return {"fields": EvrakField().model_dump()}

    # 3. Compliance Node (no LLM: pure, reproducible set subtraction)
    async def check_compliance_node(state: DocumentAnalysisState) -> dict[str, Any]:
        logger.info("Running Compliance Check Node...")
        try:
            fields = EvrakField(**(state.get("fields") or {}))
            report = check_required_fields(
                state.get("document_type", DocumentType.OTHER.value), fields
            )
            return {
                "missing_fields": [item.model_dump() for item in report.missing_fields],
                "compliance_status": report.status.value,
                "checked_field_count": report.checked_field_count,
            }
        except Exception:
            logger.exception("Compliance Check Node failed")
            return {
                "missing_fields": [],
                "compliance_status": ComplianceStatus.INCOMPLETE.value,
                "checked_field_count": 0,
            }

    # 4. Legislation Retrieval Node
    async def retrieve_mevzuat_node(state: DocumentAnalysisState) -> dict[str, Any]:
        if mevzuat_retriever is None:
            logger.info("No mevzuat retriever configured; skipping retrieval.")
            return {"mevzuat_documents": []}

        logger.info("Running Mevzuat Retrieval Node...")
        try:
            query = _build_mevzuat_query(state)
            documents = await mevzuat_retriever.retrieve(
                query, limit=MEVZUAT_RESULT_LIMIT
            )
            logger.info("Retrieved %d mevzuat excerpt(s).", len(documents))
            return {"mevzuat_documents": documents}
        except Exception:
            logger.exception("Mevzuat Retrieval Node failed")
            return {"mevzuat_documents": []}

    # 5. Legislation Suggestion Node
    async def suggest_mevzuat_node(state: DocumentAnalysisState) -> dict[str, Any]:
        documents = state.get("mevzuat_documents") or []
        if not documents:
            logger.info("No mevzuat excerpts available; skipping suggestion.")
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
            f"MEVZUAT ALINTILARI:\n\"\"\"\n{excerpts}\n\"\"\"\n\n"
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
            return {
                "mevzuat_suggestions": [item.model_dump() for item in res.suggestions]
            }
        except Exception:
            logger.exception("Mevzuat Suggestion Node failed")
            # Degrade to the raw citations rather than losing requirement 5 entirely.
            return {
                "mevzuat_suggestions": [
                    {
                        "mevzuat": document.metadata.get("mevzuat", "Bilinmeyen kaynak"),
                        "aciklama": "İlgili olabilecek mevzuat alıntısı (otomatik açıklama üretilemedi).",
                    }
                    for document in documents
                ]
            }

    builder = StateGraph(DocumentAnalysisState)
    builder.add_node("classify", classify_node)
    builder.add_node("extract_field", extract_field_node)
    builder.add_node("check_compliance", check_compliance_node)
    builder.add_node("retrieve_mevzuat", retrieve_mevzuat_node)
    builder.add_node("suggest_mevzuat", suggest_mevzuat_node)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "extract_field")
    builder.add_edge("extract_field", "check_compliance")
    builder.add_edge("check_compliance", "retrieve_mevzuat")
    builder.add_edge("retrieve_mevzuat", "suggest_mevzuat")
    builder.add_edge("suggest_mevzuat", END)

    return builder.compile()
