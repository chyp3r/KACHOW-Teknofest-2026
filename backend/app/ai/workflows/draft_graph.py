import logging
from typing import Any, Dict, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.editor import EditorAgent
from app.ai.agents.writer import WriterAgent
from app.ai.agents.reflection import ReflectionAgent
from app.ai.agents.evaluator import EvaluatorAgent
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class DraftState(TypedDict):
    """LangGraph State representing the document drafting/writing workflow context."""

    context: str  # Context gathered during RAG
    instructions: str  # User prompt/guidelines
    draft: str
    edit_feedback: str
    needs_revision: bool
    confidence_score: float
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
        description="Tüm düzeltmeleri ve parlatmaları içeren nihai Türkçe resmi yazı/taslak."
    )
    confidence_score: float = Field(
        description="Yazının doğruluğu ve kalitesine verilen güven skoru (0.0 ile 100.0 arasında)."
    )


def create_draft_graph(llm_client: BaseLLMClient):
    """Create and compile the LangGraph document drafting/generation workflow
    utilizing Writer, Editor, Reflection, and Evaluator agent roles.

    Flow: START -> Writer -> Editor -> (Needs Revision? Loop Writer : Reflection) -> Evaluator -> END
    """
    writer_agent = WriterAgent(llm_client)
    editor_agent = EditorAgent(llm_client)
    reflection_agent = ReflectionAgent(llm_client)
    evaluator_agent = EvaluatorAgent(llm_client)

    # 1. Writer Node
    async def writer_node(state: DraftState) -> Dict[str, Any]:
        logger.info("Running Writer Node...")
        attempts = state.get("attempts", 0)
        feedback = state.get("edit_feedback", "")

        # Incorporate editor feedback if we are in a revision loop
        if attempts > 0 and feedback:
            prompt = (
                f"Sana verilen ilk yönergeler: \"{state['instructions']}\"\n"
                f"Şu ana kadar yazdığın taslak:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
                f"Editör taslağı inceledi ve şu düzeltmeleri yapmanı istedi: \"{feedback}\"\n"
                "Lütfen bu geri bildirimleri uygulayarak taslağı baştan yaz ve daha kaliteli bir metin ortaya çıkart."
            )
        else:
            prompt = (
                f"Yönergeler: \"{state['instructions']}\"\n\n"
                f"Kullanabileceğin Bilgi Kaynağı/Bağlam:\n\"\"\"\n{state['context']}\n\"\"\"\n\n"
                "Lütfen bu bağlama sadık kalarak, yönergelere uygun resmi, kurumsal ve akıcı bir Türkçe yazı taslağı oluştur."
            )

        try:
            draft = await writer_agent.run(messages=prompt, temperature=0.7)
            return {"draft": draft, "attempts": attempts + 1}
        except Exception as e:
            logger.error(f"Writer Node failed: {e}", exc_info=True)
            return {"draft": "Taslak oluşturulamadı.", "attempts": attempts + 1}

    # 2. Editor Node
    async def editor_node(state: DraftState) -> Dict[str, Any]:
        logger.info("Running Editor Node...")
        prompt = (
            f"Taslak Metin:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Bu taslağı kurumsal dil, Türkçe yazım kuralları, noktalama ve akıcılık yönünden denetle. "
            "Ciddi bir eksiklik veya düzeltilmesi gereken hata varsa bunu belirt ve revizyon iste."
        )
        try:
            res: EditorOutput = await editor_agent.run_structured(
                messages=prompt, response_model=EditorOutput
            )
            return {
                "needs_revision": res.needs_revision,
                "edit_feedback": res.feedback,
            }
        except Exception as e:
            logger.error(f"Editor Node failed: {e}", exc_info=True)
            return {"needs_revision": False, "edit_feedback": ""}

    # 3. Reflection Node (Self-Correction / Critique)
    async def reflection_node(state: DraftState) -> Dict[str, Any]:
        logger.info("Running Reflection Node...")
        # Self-critique the draft to remove repetitive statements and enhance structure
        prompt = (
            f"Mevcut Taslak:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Lütfen bu taslağı kendi kendine eleştir. Resmi/kurumsal dile uymayan, tekrara düşen "
            "veya anlam karmaşası yaratan cümleleri tespit et. Metni daha vurucu ve profesyonel "
            "hale getirecek şekilde düzeltilmiş metni doğrudan çıktı olarak ver."
        )
        try:
            refined_draft = await reflection_agent.run(
                messages=prompt, temperature=0.3
            )
            return {"draft": refined_draft}
        except Exception as e:
            logger.error(f"Reflection Node failed: {e}", exc_info=True)
            return {}

    # 4. Evaluator Node
    async def evaluator_node(state: DraftState) -> Dict[str, Any]:
        logger.info("Running Evaluator Node...")
        prompt = (
            f"Nihai Metin:\n\"\"\"\n{state['draft']}\n\"\"\"\n\n"
            "Bu metni son bir kez incele. Metnin nihai halini parlatılmış olarak ver ve "
            "metnin genel kalitesine, resmiyetine ve doğruluğuna 0.0 ile 100.0 arasında bir güven skoru ata."
        )
        try:
            res: EvaluatorOutput = await evaluator_agent.run_structured(
                messages=prompt, response_model=EvaluatorOutput
            )
            return {
                "draft": res.final_draft,
                "confidence_score": res.confidence_score,
            }
        except Exception as e:
            logger.error(f"Evaluator Node failed: {e}", exc_info=True)
            return {"confidence_score": 80.0}

    # Conditional Routing Logic
    def route_after_edit(state: DraftState) -> str:
        needs_rev = state.get("needs_revision", False)
        attempts = state.get("attempts", 0)

        # If editor requests revision and we haven't hit maximum limit (e.g. 2 attempts), rewrite
        if needs_rev and attempts < 2:
            logger.warning(
                f"Editor requested revision (Attempt {attempts}). Feedback: {state.get('edit_feedback')}. Routing to Writer..."
            )
            return "rewrite"

        logger.info("Draft accepted or max revision attempts hit. Routing to Reflection.")
        return "reflection"

    # Define Graph
    builder = StateGraph(DraftState)
    builder.add_node("writer", writer_node)
    builder.add_node("editor", editor_node)
    builder.add_node("reflection", reflection_node)
    builder.add_node("evaluator", evaluator_node)

    builder.add_edge(START, "writer")
    builder.add_edge("writer", "editor")

    builder.add_conditional_edges(
        "editor",
        route_after_edit,
        {
            "rewrite": "writer",
            "reflection": "reflection",
        },
    )
    builder.add_edge("reflection", "evaluator")
    builder.add_edge("evaluator", END)

    return builder.compile()

