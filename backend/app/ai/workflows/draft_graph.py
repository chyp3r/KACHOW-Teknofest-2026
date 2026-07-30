import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

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

MAX_REVISION_ATTEMPTS = 2
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
    return json.dumps(classification, ensure_ascii=False, indent=2, sort_keys=True)


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
            }

        context = state.get("context", "").strip()
        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "context": context,
            "instructions": instructions,
            "requires_human_approval": not bool(context) or type_source == "fallback",
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "writer"

    # 2. Writer Node
    async def writer_node(state: DraftState) -> dict[str, Any]:
        logger.info("Running Writer Node...")
        attempts = state.get("attempts", 0)
        feedback = state.get("edit_feedback", "")
        source_document = state["source_document"]
        classification = _format_classification(state.get("classification", {}))
        context = state.get("context") or "Doğrulanmış ek RAG bağlamı bulunamadı."
        correspondence_profile = format_correspondence_profile(
            state["correspondence_type"]
        )

        # Incorporate editor feedback if we are in a revision loop
        if attempts > 0 and feedback:
            prompt = (
                f'Gelen Evrak:\n"""\n{source_document}\n"""\n\n'
                f"Belge Analizi:\n{classification}\n\n"
                f"İstenen Yazışma Türü:\n{correspondence_profile}\n\n"
                f'Doğrulanmış RAG Bağlamı:\n"""\n{context}\n"""\n\n'
                f"İlk Yönergeler: \"{state['instructions']}\"\n"
                f"Şu ana kadar yazdığın taslak:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
                f'Editör taslağı inceledi ve şu düzeltmeleri yapmanı istedi: "{feedback}"\n'
                "Geri bildirimi uygula; ancak gelen evrakta veya doğrulanmış bağlamda bulunmayan "
                "hiçbir kişi, tarih, kurum, mevzuat, sayı ya da olay ekleme. Eksik bilgiyi açıkça belirt."
            )
        else:
            prompt = (
                f'Gelen Evrak:\n"""\n{source_document}\n"""\n\n'
                f"Belge Analizi:\n{classification}\n\n"
                f"İstenen Yazışma Türü:\n{correspondence_profile}\n\n"
                f'Doğrulanmış RAG Bağlamı:\n"""\n{context}\n"""\n\n'
                f"Yönergeler: \"{state['instructions']}\"\n\n"
                "Yalnızca gelen evrak ve doğrulanmış bağlamdaki bilgilere dayanarak seçilen "
                "türde resmî, kurumsal ve akıcı bir Türkçe taslak oluştur. Kaynaklarda bulunmayan "
                "bilgileri uydurma; cevap için zorunlu bir bilgi eksikse bunu açıkça belirt."
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
    async def editor_node(state: DraftState) -> dict[str, Any]:
        logger.info("Running Editor Node...")
        prompt = (
            f"Gelen Evrak:\n\"\"\"\n{state['source_document']}\n\"\"\"\n\n"
            f"Belge Analizi:\n{_format_classification(state.get('classification', {}))}\n\n"
            f"İstenen Yazışma Türü:\n{format_correspondence_profile(state['correspondence_type'])}\n\n"
            f"Doğrulanmış RAG Bağlamı:\n\"\"\"\n{state.get('context') or 'Ek bağlam yok.'}\n\"\"\"\n\n"
            f"Taslak Metin:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Taslağı seçilen yazışma türünün amacı/yapısı, kaynaklara sadakat, kurumsal dil, "
            "Türkçe yazım kuralları, noktalama ve akıcılık yönünden denetle. Kaynaklarda "
            "bulunmayan bir iddia veya cevap için zorunlu eksik bilgi varsa revizyon iste ve "
            "bunu geri bildirimde açıkça belirt. Yapılandırılmış yanıtta needs_revision "
            "alanını mutlaka true veya false olarak doldur; feedback alanını en fazla üç "
            "kısa cümleyle sınırla."
        )
        try:
            res: EditorOutput = await editor_agent.run_structured(
                messages=prompt,
                response_model=EditorOutput,
                temperature=0.0,
            )
            return {
                "needs_revision": res.needs_revision,
                "edit_feedback": res.feedback,
                "requires_human_approval": (
                    state.get("requires_human_approval", False)
                    or (
                        res.needs_revision
                        and state.get("attempts", 0) >= MAX_REVISION_ATTEMPTS
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
    async def reflection_node(state: DraftState) -> dict[str, Any]:
        logger.info("Running Reflection Node...")
        prompt = (
            f"Gelen Evrak:\n\"\"\"\n{state['source_document']}\n\"\"\"\n\n"
            f"İstenen Yazışma Türü:\n{format_correspondence_profile(state['correspondence_type'])}\n\n"
            f"Doğrulanmış RAG Bağlamı:\n\"\"\"\n{state.get('context') or 'Ek bağlam yok.'}\n\"\"\"\n\n"
            f"Mevcut Taslak:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Taslağı seçilen yazışma türüne uygunluk, kaynaklara sadakat, resmî dil, tekrar ve "
            "anlam bütünlüğü yönünden eleştir. Yalnızca gelen evrak ve doğrulanmış bağlamla "
            "desteklenen bilgileri koruyarak düzeltilmiş metni doğrudan çıktı olarak ver."
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
    async def evaluator_node(state: DraftState) -> dict[str, Any]:
        logger.info("Running Evaluator Node...")
        prompt = (
            f"Gelen Evrak:\n\"\"\"\n{state['source_document']}\n\"\"\"\n\n"
            f"Belge Analizi:\n{_format_classification(state.get('classification', {}))}\n\n"
            f"İstenen Yazışma Türü:\n{format_correspondence_profile(state['correspondence_type'])}\n\n"
            f"Doğrulanmış RAG Bağlamı:\n\"\"\"\n{state.get('context') or 'Ek bağlam yok.'}\n\"\"\"\n\n"
            f"Nihai Metin:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Metni seçilen yazışma türüne uygunluk, kaynaklara sadakat, eksiksizlik, kurumsal "
            "dil ve doğruluk açısından son kez incele. Nihai metni, 0–100 güven skorunu, insan "
            "onayı gereksinimini ve kısa gerekçeyi döndür. Kaynaklarda bulunmayan bilgi varsa "
            "güven skorunu düşür ve insan onayı iste. Tüm yapılandırılmış alanları eksiksiz "
            "doldur ve evaluation_notes alanını en fazla iki kısa cümleyle sınırla."
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

        if needs_rev and attempts < MAX_REVISION_ATTEMPTS:
            logger.warning(
                f"Editor requested revision (Attempt {attempts}). Feedback: {state.get('edit_feedback')}. Routing to Writer..."
            )
            return "rewrite"

        logger.info(
            "Draft accepted or max revision attempts hit. Routing to Reflection."
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
            "rewrite": "writer",
            "reflection": "reflection",
            "end": END,
        },
    )
    builder.add_edge("reflection", "evaluator")
    builder.add_edge("evaluator", END)

    return builder.compile()
