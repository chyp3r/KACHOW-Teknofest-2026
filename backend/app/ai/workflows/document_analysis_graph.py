import asyncio
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
    DOCUMENT_TYPE_QUERY_TERMS,
    EvrakField,
    check_required_fields,
    detect_structural_signal,
    format_parsed_fields,
    format_structural_signal,
    merge_parsed_over_model,
    parse_labelled_fields,
)
from app.ai.agents.guardrail_judge import GuardrailJudgeAgent
from app.ai.guardrails.llm_nuance import judge_input_sensitivity
from app.ai.guardrails.sensitivity import SensitivityAssessment
from app.ai.guardrails.sensitivity import assess as assess_sensitivity
from app.ai.llms.base import BaseLLMClient
from app.ai.policy.budget import node_budget
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.events import emit_node_end, emit_node_error, emit_node_start, emit_partial
from app.ai.workflows.resilience import (
    IO_RETRY,
    LLM_RETRY,
    TRANSIENT_ERRORS,
    node_timeout,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.core.enums.sensitivity_level import SensitivityLevel

logger = logging.getLogger(__name__)

#: Header fields sit on the first page and the imza/ek block at the very end;
#: the middle body matters for the summary, not for field extraction.
HEAD_CHAR_BUDGET = 6000
TAIL_CHAR_BUDGET = 1500
MEVZUAT_RESULT_LIMIT = 3

#: The merged classify+extract call emits a nested object with a dozen fields.
ANALYSIS_MAX_TOKENS = 1536

#: Share of the suggest_mevzuat budget the model call may use, leaving the rest
#: for the node's own degradation path. Without this the node's timeout fires
#: outside its try/except -- where its fallback cannot reach it -- and the whole
#: analysis fails over the optional half of requirement 5.
SUGGESTION_BUDGET_SHARE = 0.85

#: Generation cap for the suggestion node. Its output is a handful of one-sentence
#: justifications, so the 1024-token default buys the model room it does not use
#: -- but 384 is too tight against real retrieved excerpts and was measured
#: costing more than it saves: qwen3.5:9b truncated mid-JSON, failed to parse,
#: retried, failed again, and the run fell through to the raw-citation fallback
#: after 2x the model's own generation time. That failure only showed up end to
#: end, not in the isolated call that first picked 384 -- worth remembering
#: before trusting an isolated timing again.
#:
#: 512 was measured against six document/missing-field combinations, two
#: repeats each: 6/6 succeeded on the first attempt, no retries. Confirmed
#: through the live endpoint against a single verified server process: three
#: consecutive uploads of the same document at 49-51s each (was 65-85s
#: uncapped), the ComplianceAgent call itself down to ~25s from ~35s, and the
#: deterministic core (type, compliance status, missing fields) identical
#: across all three. Lowering MEVZUAT_RESULT_LIMIT was measured too and
#: rejected: it saves ~2s and *changes* the answer, which is not the same kind
#: of win as a cap that reproduces the uncapped text.
SUGGESTION_MAX_TOKENS = 512


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
    sensitivity_assessment: dict[str, Any]


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

    Built from the document-type label, the subject and the type's own legislation
    vocabulary rather than from a model rewrite: those are literal tokens in the
    corpus, which is what the BM25 half of the hybrid retriever matches best.

    The vocabulary is per type (`DOCUMENT_TYPE_QUERY_TERMS`) rather than one fixed
    string. The fixed version was written when the corpus held a single realistic
    target, the correspondence regulation, so its terms were harmless in every
    query. Against the expanded corpus they became a bias: measured over the sample
    types, the fixed suffix pulled leave requests to the data-protection law and
    petitions to the civil-service law, while dropping it instead cost the
    regulation its own document types. Per-type terms are what recovers both.

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

    try:
        document_type = DocumentType(state.get("document_type", DocumentType.OTHER.value))
    except ValueError:
        document_type = DocumentType.OTHER
    parts.append(DOCUMENT_TYPE_QUERY_TERMS[document_type])

    return " ".join(parts).strip()


def _render_mevzuat_excerpts(documents: list[Document]) -> str:
    """Render retrieved legislation excerpts as prompt/display context.

    Args:
        documents: Documents returned by the hybrid retriever.

    Returns:
        The excerpts joined into one string, or an empty string when none.
    """
    parts: list[str] = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("mevzuat", "bilinmiyor")
        parts.append(f"[ALINTI {index}] (Kaynak: {source})\n{document.page_content}")
    return "\n\n".join(parts)


def create_document_analysis_graph(
    llm_client: BaseLLMClient,
    mevzuat_retriever: Optional[HybridRetriever] = None,
    reasoning_llm_client: Optional[BaseLLMClient] = None,
    fast_llm_client: Optional[BaseLLMClient] = None,
):
    """Create and compile the incoming-document analysis workflow.

    Flow::

        START -> analyze -+-> check_compliance -+-> suggest_mevzuat -> END
                          |-> retrieve_mevzuat -/
                          \\-> scan_sensitivity -----------------------> END

    Compliance checking is pure computation and legislation retrieval is network
    I/O, so they run as concurrent branches. They write disjoint state keys,
    which is what makes the fan-out safe without custom reducers.
    Sensitivity scanning is also pure computation (deterministic PII/marking
    detection, no LLM call) and writes its own disjoint key
    (``sensitivity_assessment``); it fans straight to END rather than into
    ``suggest_mevzuat`` because nothing downstream in this sub-graph needs to
    block on it, and LangGraph merges every branch's output into the same
    final state regardless of which edge reaches END.

    Args:
        llm_client: The LLM used for document analysis.
        mevzuat_retriever: Optional legislation retriever. When omitted, the two
            legislation nodes degrade to no-ops and the rest still runs.
        reasoning_llm_client: Optional separate client for the legislation
            suggestion step. Defaults to ``llm_client``.
        fast_llm_client: Optional fast-tier client. When the quality tier fails
            both the merged and classification-only structured calls, one more
            attempt runs on the fast tier before dropping to
            ``DocumentType.OTHER`` -- a third, cheap rung under the existing
            two-tier degradation ladder, only paid on the failure path.

    Returns:
        The compiled LangGraph workflow.
    """
    classifier_agent = ClassifierAgent(llm_client)
    compliance_agent = ComplianceAgent(reasoning_llm_client or llm_client)
    fallback_classifier_agent = ClassifierAgent(fast_llm_client) if fast_llm_client else None
    # Fast tier, same reasoning as fallback_classifier_agent -- a label-sized
    # verdict, not document text, so the quality tier buys nothing here.
    guardrail_judge_agent = GuardrailJudgeAgent(fast_llm_client or llm_client)

    @node_timeout("analyze")
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
            # circular needs explicit discriminators. Without them the model falls
            # back to official_letter, which the paragraph above names as the
            # default for inter-institution correspondence -- and a genelge *is*
            # structurally an official letter, so only the addressee and the
            # rule-setting language separate them. detect_structural_signal already
            # reported DAĞITIM, so the observation was present and only the
            # criterion to act on it was missing. Measured on qwen3.5:9b over the
            # sample corpus: type accuracy 11/12 -> 12/12, stable across three
            # repeats (36/36).
            "- circular: tek bir muhataba değil 'DAĞITIM YERLERİNE' / 'Dağıtım' "
            "listesine gönderilen, tek bir olayı değil genel uygulama usul ve "
            "esaslarını düzenleyen yazı (genelge). Muhatabı dağıtım listesi olan ve "
            "'usul ve esaslar', 'tüm birimler' gibi genel düzenleme ifadeleri "
            "taşıyan yazıyı official_letter değil circular say.\n"
            "- directive: belirli bir birime verilen, uyulması zorunlu somut iş "
            "talimatı.\n"
            "- complaint: şikayet bildirimi. report: rapor. minutes: tutanak.\n"
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
        except TRANSIENT_ERRORS:
            # A dropped connection affects every tier of this ladder equally
            # (they all talk to the same Ollama instance), so retrying the
            # whole node once the connection is back beats cycling through
            # degradation tiers that would hit the same error.
            logger.warning("Document Analysis Node hit a transient error; retrying.")
            raise
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
            except TRANSIENT_ERRORS:
                logger.warning("Document Analysis Node hit a transient error; retrying.")
                raise
            except Exception:
                if fallback_classifier_agent is not None:
                    logger.warning(
                        "Classification-only analysis also failed; trying the "
                        "fast tier once before giving up.",
                        exc_info=True,
                    )
                    try:
                        fast_fallback: DocumentClassificationOutput = (
                            await fallback_classifier_agent.run_structured(
                                messages=prompt,
                                response_model=DocumentClassificationOutput,
                                temperature=0.0,
                                max_retries=1,
                            )
                        )
                        document_type = DocumentType(fast_fallback.document_type)
                        summary = fast_fallback.summary
                    except TRANSIENT_ERRORS:
                        logger.warning("Document Analysis Node hit a transient error; retrying.")
                        raise
                    except Exception:
                        logger.exception("Document Analysis Node failed on every tier")
                        document_type = DocumentType.OTHER
                        summary = "Evrak özeti çıkarılamadı."
                else:
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

    @node_timeout("scan_sensitivity")
    async def scan_sensitivity_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Assess confidentiality marking and PII exposure, then ask the
        nuance judge whether the document reads as sensitive in meaning
        even where no pattern matched.

        Independent branch off ``analyze`` (see the flow diagram above):
        nothing downstream in this sub-graph needs to block on it, so it
        fans straight to END rather than merging into ``suggest_mevzuat``'s
        fan-in. ``DocumentService`` reads ``sensitivity_assessment`` off the
        final merged state alongside every other branch's output.
        """
        logger.info("Running Sensitivity Scan Node...")
        input_text = state.get("input_text", "")
        try:
            fields = EvrakField(**(state.get("fields") or {}))
            assessment = assess_sensitivity(fields=fields, text=input_text)
        except Exception:
            logger.exception("Sensitivity Scan Node failed")
            assessment = SensitivityAssessment(
                level=SensitivityLevel.UNMARKED, requires_review=False
            )

        if not assessment.requires_review:
            # Only worth asking when the deterministic layer didn't already
            # flag the document -- this is specifically the "no pattern
            # matched but it reads as sensitive" case; a document already
            # routed to review gains nothing from a second opinion here.
            judge_verdict = await judge_input_sensitivity(guardrail_judge_agent, text=input_text)
            if judge_verdict is not None and judge_verdict.sensitive and judge_verdict.confidence >= 0.5:
                assessment = assessment.model_copy(
                    update={
                        "requires_review": True,
                        "reasons": [
                            *assessment.reasons,
                            f"llm-judge anlam bazlı hassasiyet: {judge_verdict.reason}",
                        ],
                    }
                )

        update = {"sensitivity_assessment": assessment.model_dump(mode="json")}
        await emit_partial(config, "sensitivity", update)
        return update

    @node_timeout("retrieve_mevzuat")
    async def retrieve_mevzuat_node(
        state: DocumentAnalysisState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Retrieve legislation excerpts for the document.

        Emits its own node_start/node_end under the "rag" node id -- the root
        cause of the frontend's "Mevzuat" panel never showing data (D1) was
        that this node previously emitted nothing at all, even though the
        excerpts it retrieves are real and used by both the draft brief and
        the analysis response's mevzuat_references.
        """
        query = _build_mevzuat_query(state)
        await emit_node_start(
            config, "rag", "Mevzuat Tarama", "Mevzuat veri tabanında ilgili maddeler taranıyor..."
        )

        if mevzuat_retriever is None:
            logger.info("No mevzuat retriever configured; skipping retrieval.")
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                "Mevzuat erişimi yapılandırılmadığı için atlandı.",
                {"search_query": query, "documents": [], "context": ""},
            )
            return {"mevzuat_documents": []}

        logger.info("Running Mevzuat Retrieval Node...")
        try:
            documents = await mevzuat_retriever.retrieve(query, limit=MEVZUAT_RESULT_LIMIT)
            logger.info("Retrieved %d mevzuat excerpt(s).", len(documents))
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                f"{len(documents)} mevzuat alıntısı bulundu.",
                {
                    "search_query": query,
                    "documents": [
                        {
                            "page_content": document.page_content,
                            "metadata": document.metadata,
                        }
                        for document in documents
                    ],
                    "context": _render_mevzuat_excerpts(documents),
                },
            )
            return {"mevzuat_documents": documents}
        except TRANSIENT_ERRORS:
            # Let the graph's IO_RETRY policy retry a dropped connection;
            # swallowing it here would mean the retry policy never fires.
            logger.warning("Mevzuat Retrieval Node hit a transient error; retrying.")
            raise
        except Exception:
            logger.exception("Mevzuat Retrieval Node failed")
            await emit_node_error(
                config,
                "rag",
                "Mevzuat Tarama",
                "Mevzuat taraması sırasında bir hata oluştu.",
                fatal=False,
            )
            return {"mevzuat_documents": []}

    @node_timeout("suggest_mevzuat")
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
            # Bounded *inside* the node, below the node's own budget, so an
            # overrun lands in the degradation path below instead of escaping to
            # node_timeout. Explaining the excerpts is the optional half of
            # requirement 5 -- the citations are already retrieved and correct --
            # so a slow model should cost the explanation, never the analysis.
            res: MevzuatSuggestionOutput = await asyncio.wait_for(
                compliance_agent.run_structured(
                    messages=prompt,
                    response_model=MevzuatSuggestionOutput,
                    temperature=0.0,
                    max_tokens=SUGGESTION_MAX_TOKENS,
                ),
                timeout=node_budget("suggest_mevzuat") * SUGGESTION_BUDGET_SHARE,
            )
            suggestions = [item.model_dump() for item in res.suggestions]
        except TRANSIENT_ERRORS:
            logger.warning("Mevzuat Suggestion Node hit a transient error; retrying.")
            raise
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
    # check_compliance is pure computation over already-fetched state and
    # never raises past its own try/except, so it carries no retry policy.
    builder.add_node("analyze", analyze_node, retry_policy=LLM_RETRY)
    builder.add_node("check_compliance", check_compliance_node)
    builder.add_node("retrieve_mevzuat", retrieve_mevzuat_node, retry_policy=IO_RETRY)
    builder.add_node("suggest_mevzuat", suggest_mevzuat_node, retry_policy=LLM_RETRY)
    builder.add_node("scan_sensitivity", scan_sensitivity_node)

    builder.add_edge(START, "analyze")
    # Fan out: compliance is CPU-bound, retrieval is network-bound, sensitivity
    # scanning is CPU-bound and independent of both.
    builder.add_edge("analyze", "check_compliance")
    builder.add_edge("analyze", "retrieve_mevzuat")
    builder.add_edge("analyze", "scan_sensitivity")
    # Fan in: LangGraph waits for both branches before running this node.
    builder.add_edge("check_compliance", "suggest_mevzuat")
    builder.add_edge("retrieve_mevzuat", "suggest_mevzuat")
    builder.add_edge("suggest_mevzuat", END)
    # Independent branch -- its own path straight to END.
    builder.add_edge("scan_sensitivity", END)

    return builder.compile()
