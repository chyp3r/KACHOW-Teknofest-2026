import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from langchain_core.runnables import RunnableConfig

from app.ai.agents.editor import EditorAgent
from app.ai.agents.evaluator import EvaluatorAgent
from app.ai.agents.reflection import ReflectionAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    resolve_correspondence_type,
)

logger = logging.getLogger(__name__)

MAX_REVISION_ATTEMPTS = 1
MIN_AUTOMATED_CONFIDENCE_SCORE = 70.0


class DraftState(TypedDict, total=False):
    """LangGraph State representing the document drafting/writing workflow context."""

    source_document: str
    classification: dict[str, Any]
    correspondence_type: str
    correspondence_type_source: str
    context: str
    instructions: str
    draft: str
    edit_feedback: str
    needs_revision: bool
    confidence_score: float
    requires_human_approval: bool
    evaluation_notes: str
    status: str
    error: str
    attempts: int
    brief: str



class EditorOutput(BaseModel):
    """Pydantic schema for editor review."""

    needs_revision: bool = Field(
        description="Yazının tekrar düzenlenmesi gerekiyor mu? True veya False."
    )
    feedback: str = Field(
        description="Düzeltilmesi gereken noktalar, biçim hataları veya yazım yanlışları geri bildirimi."
    )


class EvaluatorOutput(BaseModel):
    """Pydantic schema for final document evaluation."""

    final_draft: str = Field(
        min_length=1,
        description="Tüm düzeltmeleri ve parlatmaları içeren nihai Türkçe resmi yazı/taslak.",
    )
    confidence_score: float = Field(
        ge=0.0,
        le=100.0,
        description="Yazının doğruluğu ve kalitesine verilen güven skoru (0.0 ile 100.0 arasında).",
    )
    requires_human_approval: bool = Field(
        default=False,
        description="Eksik veya doğrulanamayan bilgi nedeniyle insan onayı gerekip gerekmediği.",
    )
    evaluation_notes: str = Field(
        default="",
        description="Güven skorunun ve insan onayı kararının kısa Türkçe gerekçesi.",
    )


def _format_classification(classification: dict[str, Any]) -> str:
    """Serialize document analysis data for grounded agent prompts."""
    if not classification:
        return "Sınıflandırma bilgisi sağlanmadı."
    
    # Pre-process classification dict to handle non-serializable Document objects and other types
    cleaned = {}
    for k, v in classification.items():
        if isinstance(v, list):
            cleaned_list = []
            for item in v:
                if hasattr(item, "page_content") and hasattr(item, "metadata"):  # LangChain Document
                    cleaned_list.append({
                        "page_content": item.page_content,
                        "metadata": item.metadata
                    })
                elif hasattr(item, "model_dump"):  # Pydantic v2
                    cleaned_list.append(item.model_dump())
                elif hasattr(item, "dict"):  # Pydantic v1
                    cleaned_list.append(item.dict())
                else:
                    cleaned_list.append(item)
            cleaned[k] = cleaned_list
        elif hasattr(v, "page_content") and hasattr(v, "metadata"):  # LangChain Document
            cleaned[k] = {
                "page_content": v.page_content,
                "metadata": v.metadata
            }
        elif hasattr(v, "model_dump"):  # Pydantic v2
            cleaned[k] = v.model_dump()
        elif hasattr(v, "dict"):  # Pydantic v1
            cleaned[k] = v.dict()
        else:
            cleaned[k] = v

    try:
        return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return str(cleaned)


def create_draft_graph(llm_client: BaseLLMClient):
    """Create and compile the LangGraph document drafting/generation workflow
    utilizing Writer, Editor, Reflection, and Evaluator agent roles.

    Flow: START -> Writer -> Editor -> (Needs Revision? Loop Writer : Reflection) -> Evaluator -> END
    """
    writer_agent = WriterAgent(llm_client)
    editor_agent = EditorAgent(llm_client)
    reflection_agent = ReflectionAgent(llm_client)
    evaluator_agent = EvaluatorAgent(llm_client)

    # 1. Input Validation Node
    async def validate_input_node(state: DraftState) -> dict[str, Any]:
        classification = state.get("classification", {})
        instructions = (
            state.get("instructions", "").strip()
            or "Gelen evraka uygun resmî ve kurumsal bir yazışma taslağı oluştur."
        )
        correspondence_type, type_source = resolve_correspondence_type(
            state.get("correspondence_type"),
            instructions,
            classification,
        )
        source_document = state.get("source_document", "").strip()
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

        context = state.get("context", "").strip()
        
        # Compile Brief (Briefing Agent / Context Builder Pattern)
        fields = classification.get("fields", {})
        if hasattr(fields, "model_dump"):
            fields = fields.model_dump()
        elif hasattr(fields, "dict"):
            fields = fields.dict()
        elif not isinstance(fields, dict):
            fields = {}

        brief = (
            f"1. Belge Türü: {classification.get('document_type_label') or classification.get('document_type') or 'Belirtilmedi'}\n"
            f"2. Belge Özeti: {classification.get('summary') or 'Özet çıkarılamadı.'}\n"
            f"3. Çıkarılan Kritik Bilgiler:\n"
            f"   - Tarih: {fields.get('tarih') or 'Bulunamadı'}\n"
            f"   - Sayı: {fields.get('sayi') or 'Bulunamadı'}\n"
            f"   - Konu: {fields.get('konu') or 'Bulunamadı'}\n"
            f"   - Muhatap: {fields.get('muhatap') or 'Bulunamadı'}\n"
            f"4. Doğrulanmış Mevzuat Bağlamı:\n\"\"\"\n{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
            f"5. Kullanıcı Talebi ve Talimatlar: {instructions}\n"
        )

        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "context": context,
            "instructions": instructions,
            "brief": brief,
            "requires_human_approval": not bool(context) or type_source == "fallback",
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "writer"

    # 2. Writer Node
    async def writer_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Writer Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        attempts = state.get("attempts", 0)
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Taslak Oluşturma",
                "message": f"[Yazar Ajanı] Taslak yazılıyor... (Deneme {attempts + 1})"
            })
        attempts = state.get("attempts", 0)
        feedback = state.get("edit_feedback", "")
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )

        # Incorporate editor feedback if we are in a revision loop
        if attempts > 0 and feedback:
            prompt = (
                f"### GÖREV:\n"
                f"Aşağıdaki 'Brief' belgesi ve editörün geri bildirimine göre taslak cevabı revize et.\n\n"
                f"### BRIEF BELGESİ:\n"
                f"{brief}\n\n"
                f"### YAZIŞMA TÜRÜ PROFILI:\n"
                f"{correspondence_profile}\n\n"
                f"### ÖNCEKİ TASLAK:\n"
                f"\"\"\"\n{state['draft']}\n\"\"\"\n\n"
                f"### EDİTÖRÜN GERİ BİLDİRİMİ:\n"
                f"\"{feedback}\"\n\n"
                "### KURALLAR:\n"
                "- Yalnızca brief içindeki bilgilere sadık kal, yeni bilgi/olay/tarih/mevzuat uydurma.\n"
                "- Editörün geri bildirimini eksiksiz uygula."
            )
        else:
            prompt = (
                f"### GÖREV:\n"
                f"Aşağıdaki 'Brief' (özet, kritik bilgiler ve mevzuat) doğrultusunda resmi ve kurumsal bir Türkçe cevap taslağı yaz.\n\n"
                f"### BRIEF BELGESİ:\n"
                f"{brief}\n\n"
                f"### YAZIŞMA TÜRÜ PROFILI:\n"
                f"{correspondence_profile}\n\n"
                "### KURALLAR:\n"
                "- Yalnızca brief içindeki bilgilere ve mevzuat bağlamına sadık kal.\n"
                "- Gelen evrak veya mevzuatta yer almayan hiçbir kişi, kurum, sayı, tarih veya olay uydurma.\n"
                "- Cevap yazısı için zorunlu olan ancak brief içinde bulunmayan eksik bilgiler varsa bunu taslak metin içinde açıkça belirt (örn. '[Tarih Eksik - Lütfen Doldurun]')."
            )

        try:
            draft = await writer_agent.run(messages=prompt, temperature=0.7)
            if not draft.strip():
                raise ValueError("WriterAgent boş taslak döndürdü.")
            return {
                "draft": draft,
                "attempts": attempts + 1,
                "status": "IN_PROGRESS",
            }
        except Exception as e:
            logger.exception("Writer Node failed")
            return {
                "draft": "",
                "attempts": attempts + 1,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": f"WriterAgent taslak üretemedi: {e}",
            }

    def route_after_writer(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "editor"

    # 3. Editor Node
    async def editor_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Editor Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Taslak Denetleme",
                "message": "[Editör Ajanı] Taslak resmi yazışma kuralları ve kaynak doğruluğu açısından denetleniyor..."
            })
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )
        prompt = (
            f"### BRIEF BELGESİ:\n"
            f"{brief}\n\n"
            f"### YAZIŞMA TÜRÜ PROFILI:\n"
            f"{correspondence_profile}\n\n"
            f"### DENETLENECEK TASLAK METİN:\n"
            f"\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "### DENETLEME VE ÇIKTI TALİMATI:\n"
            "Taslağı brief belgesine uygunluk, kaynaklara sadakat, kurumsal dil, Türkçe yazım kuralları, noktalama ve akıcılık yönünden incele.\n"
            "Eğer brief dışından uydurulmuş bilgiler varsa veya taslak eksikse revizyon iste ('needs_revision': true) ve gerekçesini 'feedback' alanına yaz.\n"
            "Taslak başarılı ise 'needs_revision': false yap."
        )
        try:
            res: EditorOutput = await editor_agent.run_structured(
                messages=prompt,
                response_model=EditorOutput,
                temperature=0.0,
            )
            if res.needs_revision:
                if status_queue:
                    await status_queue.put({
                        "event": "node_start",
                        "node": "draft",
                        "label": "Taslak Denetleme",
                        "message": f"[Editör Ajanı] Düzeltme talep edildi: {res.feedback}"
                    })
            return {
                "needs_revision": res.needs_revision,
                "edit_feedback": res.feedback,
                "requires_human_approval": (
                    state.get("requires_human_approval", False)
                    or (
                        res.needs_revision
                        and state.get("attempts", 0) > MAX_REVISION_ATTEMPTS
                    )
                ),
            }
        except Exception as e:
            logger.exception("Editor Node failed")
            return {
                "needs_revision": False,
                "edit_feedback": "",
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "NEEDS_HUMAN_APPROVAL",
                "error": f"EditorAgent taslağı doğrulayamadı: {e}",
            }

    # 4. Reflection Node (Self-Correction / Critique)
    async def reflection_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Reflection Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Taslak İyileştirme",
                "message": "[Kritik Ajanı] Taslak metni editör geri bildirimiyle parlatılıyor ve düzeltiliyor..."
            })
        feedback = state.get("edit_feedback", "")
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )
        prompt = (
            f"### BRIEF BELGESİ:\n"
            f"{brief}\n\n"
            f"### YAZIŞMA TÜRÜ PROFILI:\n"
            f"{correspondence_profile}\n\n"
            f"### MEVCUT TASLAK:\n"
            f"\"\"\"\n{state['draft']}\n\"\"\"\n\n"
        )
        if feedback:
            prompt += f"### EDİTÖRÜN GERİ BİLDİRİMİ:\n\"{feedback}\"\n\nLütfen bu geri bildirimi dikkate alarak taslağı düzeltin.\n\n"
            
        prompt += (
            "### TALİMAT:\n"
            "Taslağı brief belgesine uygunluk, kaynaklara sadakat, resmî dil, tekrar ve anlam bütünlüğü yönünden düzeltip geliştir.\n"
            "Yeni bilgi uydurmadan parlatılmış nihai metni doğrudan çıktı olarak ver."
        )
        try:
            refined_draft = await reflection_agent.run(messages=prompt, temperature=0.3)
            if not refined_draft.strip():
                raise ValueError("ReflectionAgent boş taslak döndürdü.")
            return {"draft": refined_draft}
        except Exception as e:
            logger.exception("Reflection Node failed")
            return {
                "requires_human_approval": True,
                "error": f"ReflectionAgent taslağı iyileştiremedi: {e}",
            }

    # 5. Evaluator Node
    async def evaluator_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Evaluator Node...")
        status_queue = config.get("configurable", {}).get("status_queue")
        if status_queue:
            await status_queue.put({
                "event": "node_start",
                "node": "draft",
                "label": "Kalite Kontrol",
                "message": "[Değerlendirici Ajanı] Nihai taslak kalite kontrol ve puanlama aşamasına alındı..."
            })
        brief = state["brief"]
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )
        prompt = (
            f"### BRIEF BELGESİ:\n"
            f"{brief}\n\n"
            f"### YAZIŞMA TÜRÜ PROFILI:\n"
            f"{correspondence_profile}\n\n"
            f"### NİHAİ TASLAK METİN:\n"
            f"\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "### DEĞERLENDİRME TALİMATI:\n"
            "Metni brief belgesine uygunluk, kaynaklara sadakat, eksiksizlik, kurumsal dil ve doğruluk açısından son kez incele.\n"
            "Nihai metni, 0–100 güven skorunu, insan onayı gereksinimini ve kısa gerekçeyi yapılandırılmış formatta döndür."
        )
        try:
            res: EvaluatorOutput = await evaluator_agent.run_structured(
                messages=prompt,
                response_model=EvaluatorOutput,
                temperature=0.0,
            )
            requires_human_approval = (
                state.get("requires_human_approval", False)
                or res.requires_human_approval
                or res.confidence_score < MIN_AUTOMATED_CONFIDENCE_SCORE
            )
            return {
                "draft": res.final_draft,
                "confidence_score": res.confidence_score,
                "requires_human_approval": requires_human_approval,
                "evaluation_notes": res.evaluation_notes,
                "status": (
                    "NEEDS_HUMAN_APPROVAL" if requires_human_approval else "COMPLETED"
                ),
            }
        except Exception as e:
            logger.exception("Evaluator Node failed")
            return {
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "NEEDS_HUMAN_APPROVAL",
                "error": f"EvaluatorAgent nihai taslağı doğrulayamadı: {e}",
            }

    # Conditional Routing Logic
    def route_after_edit(state: DraftState) -> str:
        if state.get("status") == "NEEDS_HUMAN_APPROVAL":
            return "end"

        needs_rev = state.get("needs_revision", False)
        attempts = state.get("attempts", 0)

        if needs_rev and attempts <= MAX_REVISION_ATTEMPTS:
            logger.warning(
                f"Editor requested revision (Attempt {attempts}). Feedback: {state.get('edit_feedback')}. Routing to Writer for refinement..."
            )
            return "writer"

        logger.info(
            "Draft accepted or max revision attempts hit. Routing to Reflection for final polish."
        )
        return "reflection"

    # Define Graph
    builder = StateGraph(DraftState)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("writer", writer_node)
    builder.add_node("editor", editor_node)
    builder.add_node("reflection", reflection_node)
    builder.add_node("evaluator", evaluator_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {
            "writer": "writer",
            "end": END,
        },
    )
    builder.add_conditional_edges(
        "writer",
        route_after_writer,
        {
            "editor": "editor",
            "end": END,
        },
    )

    builder.add_conditional_edges(
        "editor",
        route_after_edit,
        {
            "writer": "writer",
            "reflection": "reflection",
            "evaluator": "evaluator",
            "end": END,
        },
    )
    builder.add_edge("reflection", "evaluator")
    builder.add_edge("evaluator", END)

    return builder.compile()
