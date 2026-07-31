import json
import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.verification import verify_draft
from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    resolve_correspondence_type,
)
from app.ai.workflows.events import emit_node_end, emit_node_start, emit_token

logger = logging.getLogger(__name__)

#: Generation budget for a draft. An official letter with header, body and
#: signature block runs 600-1200 tokens; the old global cap of 1024 truncated
#: the longer ones mid-sentence.
DRAFT_MAX_TOKENS = 2048


class DraftState(TypedDict, total=False):
    """LangGraph state for the drafting workflow."""

    source_document: str
    classification: dict[str, Any]
    correspondence_type: str
    correspondence_type_source: str
    context: str
    instructions: str
    draft: str
    confidence_score: float
    requires_human_approval: bool
    evaluation_notes: str
    verification: dict[str, Any]
    status: str
    error: str
    attempts: int
    brief: str


def _format_classification(classification: dict[str, Any]) -> str:
    """Serialize analysis output for grounded agent prompts.

    Args:
        classification: The analysis result, which may contain LangChain
            Documents and Pydantic models alongside plain values.

    Returns:
        Pretty-printed JSON, or a repr when the structure resists serialization.
    """
    if not classification:
        return "Sınıflandırma bilgisi sağlanmadı."

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        if hasattr(value, "page_content") and hasattr(value, "metadata"):
            return {"page_content": value.page_content, "metadata": value.metadata}
        if hasattr(value, "model_dump"):
            return _clean(value.model_dump())
        return value

    cleaned = _clean(classification)
    try:
        return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(cleaned)


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Return the extracted header fields as a plain dict."""
    fields = classification.get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_brief(
    classification: dict[str, Any], context: str, instructions: str
) -> str:
    """Compose the grounding brief handed to the writer.

    Args:
        classification: Analysis output for the incoming document.
        context: Retrieved legislation excerpts.
        instructions: The user's drafting instructions.

    Returns:
        The brief text.
    """
    fields = _coerce_fields(classification)
    missing = classification.get("missing_fields") or []
    missing_labels = ", ".join(
        item.get("label", "") for item in missing if isinstance(item, dict)
    )

    return (
        f"1. Belge Türü: "
        f"{classification.get('document_type_label') or classification.get('document_type') or 'Belirtilmedi'}\n"
        f"2. Belge Özeti: {classification.get('summary') or 'Özet çıkarılamadı.'}\n"
        f"3. Çıkarılan Kritik Bilgiler:\n"
        f"   - Tarih: {fields.get('tarih') or 'Bulunamadı'}\n"
        f"   - Sayı: {fields.get('sayi') or 'Bulunamadı'}\n"
        f"   - Konu: {fields.get('konu') or 'Bulunamadı'}\n"
        f"   - Muhatap: {fields.get('muhatap') or 'Bulunamadı'}\n"
        f"   - Gönderen Kurum: {fields.get('gonderen_kurum') or 'Bulunamadı'}\n"
        f"   - İmza Sahibi: {fields.get('imza_sahibi') or 'Bulunamadı'}"
        f" ({fields.get('imza_unvani') or 'unvan yok'})\n"
        f"4. Evrakta Tespit Edilen Eksik Alanlar: {missing_labels or 'yok'}\n"
        f'5. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
        f"6. Kullanıcı Talebi ve Talimatlar: {instructions}\n"
    )


def create_draft_graph(llm_client: BaseLLMClient):
    """Create and compile the drafting workflow.

    Flow: START -> validate_input -> writer -> verify -> END

    The former LLM editor node is now :func:`app.ai.verification.verify_draft`, a
    pure function. That removes a second full generation of the same text from
    the critical path -- the largest single latency cost in the pipeline -- and
    replaces self-graded fluency with an actual groundedness check.

    Args:
        llm_client: The LLM used by the writer agent.

    Returns:
        The compiled LangGraph workflow.
    """
    writer_agent = WriterAgent(llm_client)

    async def validate_input_node(state: DraftState) -> dict[str, Any]:
        classification = state.get("classification") or {}
        instructions = (
            (state.get("instructions") or "").strip()
            or "Gelen evraka uygun resmî ve kurumsal bir yazışma taslağı oluştur."
        )
        correspondence_type, type_source = resolve_correspondence_type(
            state.get("correspondence_type"), instructions, classification
        )

        source_document = (state.get("source_document") or "").strip()
        if not source_document:
            error = "Gelen evrak içeriği sağlanmadığı için taslak oluşturulamadı."
            logger.error(error)
            return {
                "correspondence_type": correspondence_type.value,
                "correspondence_type_source": type_source,
                "draft": "",
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": error,
                "attempts": state.get("attempts", 0),
                "brief": "",
            }

        context = (state.get("context") or "").strip()
        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "context": context,
            "instructions": instructions,
            "brief": _build_brief(classification, context, instructions),
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "writer"

    async def writer_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Writer Node...")
        await emit_node_start(
            config, "draft", "Taslak Oluşturma", "[Yazar Ajanı] Taslak yazılıyor..."
        )

        attempts = state.get("attempts", 0)
        is_other = state.get("correspondence_type") == "other_official"

        if is_other:
            rules = (
                "- Yazışma türü 'Diğer resmî yazışma' olduğu için, brief'te bulunmayan "
                "tamamlayıcı bilgileri genel kurumsal bilgi birikiminle tamamlayabilirsin.\n"
                "- Resmî yazı standartlarına uygunluğu sağlamak için makul tamamlamalar yapabilirsin."
            )
        else:
            rules = (
                "- Yalnızca brief içindeki bilgilere ve mevzuat bağlamına sadık kal.\n"
                "- Gelen evrakta veya mevzuatta yer almayan hiçbir kişi, kurum, sayı, "
                "tarih veya olay uydurma.\n"
                "- Zorunlu olup brief'te bulunmayan bilgileri köşeli parantezli yer "
                "tutucu olarak bırak (örn. '[Tarih Eksik - Lütfen Doldurun]')."
            )

        prompt = (
            "### GÖREV:\n"
            "Aşağıdaki brief doğrultusunda resmî ve kurumsal bir Türkçe yazı taslağı yaz.\n\n"
            f"### BRIEF BELGESİ:\n{state['brief']}\n\n"
            f"### YAZIŞMA TÜRÜ PROFİLİ:\n"
            f"{format_correspondence_profile(state['correspondence_type'])}\n\n"
            f"### KURALLAR:\n{rules}"
        )

        # Streamed rather than awaited whole: the draft is the longest single
        # generation in the system, and forwarding chunks is what makes the UI
        # feel live instead of frozen behind a spinner.
        chunks: list[str] = []
        try:
            async for chunk in writer_agent.stream(
                messages=prompt, temperature=0.4, max_tokens=DRAFT_MAX_TOKENS
            ):
                chunks.append(chunk)
                await emit_token(config, "draft", chunk)

            draft = "".join(chunks).strip()
            if not draft:
                raise ValueError("WriterAgent boş taslak döndürdü.")

            return {"draft": draft, "attempts": attempts + 1, "status": "IN_PROGRESS"}
        except Exception as exc:
            logger.exception("Writer Node failed")
            return {
                "draft": "".join(chunks).strip(),
                "attempts": attempts + 1,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": f"WriterAgent taslak üretemedi: {exc}",
            }

    def route_after_writer(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "verify"

    async def verify_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Draft Verification Node...")
        await emit_node_start(
            config,
            "draft",
            "Taslak Doğrulama",
            "[Doğrulayıcı] Taslak kaynak evrak ve mevzuata karşı denetleniyor...",
        )

        report = verify_draft(
            state.get("draft", ""),
            source_document=state.get("source_document", ""),
            context=state.get("context", ""),
            classification=state.get("classification") or {},
            instructions=state.get("instructions", ""),
            strict=state.get("correspondence_type") != "other_official",
        )

        # An unresolved correspondence type means the system guessed which kind
        # of letter to write, which is itself grounds for review.
        requires_approval = (
            report.requires_human_approval
            or state.get("correspondence_type_source") == "fallback"
            or not state.get("context")
        )

        update = {
            "confidence_score": report.confidence_score,
            "requires_human_approval": requires_approval,
            "evaluation_notes": report.evaluation_notes,
            "verification": report.model_dump(),
            "status": "NEEDS_HUMAN_APPROVAL" if requires_approval else "COMPLETED",
        }

        await emit_node_end(
            config,
            "draft",
            "Taslak Oluşturma",
            "Taslak hazırlandı ve doğrulandı.",
            {"draft": state.get("draft", ""), **update},
        )
        return update

    builder = StateGraph(DraftState)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("writer", writer_node)
    builder.add_node("verify", verify_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input", route_after_validation, {"writer": "writer", "end": END}
    )
    builder.add_conditional_edges(
        "writer", route_after_writer, {"verify": "verify", "end": END}
    )
    builder.add_edge("verify", END)

    return builder.compile()
