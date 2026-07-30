import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.orchestrator import OrchestratorAgent
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class PlanningState(TypedDict):
    """LangGraph State representing the main Orchestrator/Planning workflow context."""

    input_text: str
    plan_steps: list[str]  # e.g., ["classification", "rag", "draft", "routing"]
    current_step_idx: int
    classification_result: dict[str, Any]
    rag_result: dict[str, Any]
    draft_result: dict[str, Any]
    routing_result: dict[str, Any]
    final_output: dict[str, Any]


class PlanOutput(BaseModel):
    """Pydantic schema for structured planning decisions."""

    required_steps: list[str] = Field(
        description="Çalıştırılması gereken adımların sıralı listesi. Şunları içerebilir: 'classification', 'rag', 'draft', 'routing'."
    )
    reasoning: str = Field(
        description="Neden bu adımların seçildiğinin Türkçe gerekçesi."
    )


def _requested_correspondence_type(
    classification: dict[str, Any],
) -> str | None:
    """Read an explicitly classified output correspondence type.

    Args:
        classification: Combined Classification Graph result.

    Returns:
        Requested correspondence type when classification metadata contains one.
    """
    metadata = classification.get("metadata", {})
    return classification.get("correspondence_type") or metadata.get(
        "correspondence_type"
    )


def create_planning_graph(
    llm_client: BaseLLMClient,
    classification_graph: Any,
    rag_graph: Any,
    draft_graph: Any,
    routing_graph: Any,
):
    """Create and compile the LangGraph master Planning/Supervisor workflow.

    Evaluates the input query, generates an execution plan, and dynamically routes
    through sub-graphs (Classification, RAG, Draft, Routing) sequentially.
    """
    orchestrator_agent = OrchestratorAgent(llm_client)

    # 1. Planning/Supervisor Node
    async def supervisor_planning_node(state: PlanningState) -> dict[str, Any]:
        logger.info("Supervisor planning task execution...")

        prompt = (
            f"Kullanıcı İsteği:\n\"\"\"\n{state['input_text']}\n\"\"\"\n\n"
            "Bu istek için hangi iş süreçlerinin çalıştırılması gerektiğini belirle.\n"
            "İş Süreçleri Kuralları:\n"
            "- Eğer ham bir dosya/belge (PDF, görsel vb.) geldiyse önce 'classification' mutlaka çalışmalıdır.\n"
            "- Eğer belgeden bilgi çıkarma veya mevzuata dayalı cevaplama gerekiyorsa 'rag' çalışmalıdır.\n"
            "- Eğer resmi bir yazı, mektup veya taslak hazırlanması gerekiyorsa 'draft' çalışmalıdır.\n"
            "- Eğer hazırlanan yazının yönlendirilmesi/aksiyonu gerekiyorsa 'routing' çalışmalıdır.\n"
            "- Eğer sadece basit bir sohbet veya bilgi dışı soruysa sadece 'rag' ve 'draft' yeterlidir.\n\n"
            "Sıralı adımları ve gerekçesini yapılandırılmış Türkçe formatta döndür."
        )

        try:
            res: PlanOutput = await orchestrator_agent.run_structured(
                messages=prompt, response_model=PlanOutput
            )
            logger.info(f"Supervisor generated plan: {res.required_steps}")
            return {
                "plan_steps": res.required_steps,
                "current_step_idx": 0,
                "classification_result": {},
                "rag_result": {},
                "draft_result": {},
                "routing_result": {},
                "final_output": {},
            }
        except Exception:
            logger.exception("Supervisor Planning Node failed")
            # Default safe plan fallback
            return {
                "plan_steps": ["classification", "rag", "draft", "routing"],
                "current_step_idx": 0,
                "classification_result": {},
                "rag_result": {},
                "draft_result": {},
                "routing_result": {},
                "final_output": {},
            }

    # 2. Sub-graph Execution Orchestration Node
    async def execute_step_node(state: PlanningState) -> dict[str, Any]:
        idx = state["current_step_idx"]
        steps = state["plan_steps"]

        if idx >= len(steps):
            return {}

        current_step = steps[idx].lower()
        logger.info(f"Executing plan step {idx + 1}/{len(steps)}: '{current_step}'")

        new_state_updates = {"current_step_idx": idx + 1}

        # Dynamically execute corresponding sub-graph
        if current_step == "classification":
            sub_res = await classification_graph.ainvoke(
                {"input_text": state["input_text"]}
            )
            new_state_updates["classification_result"] = sub_res

        elif current_step == "rag":
            # Extract query: use classification summary if available, otherwise original text
            query = (
                state.get("classification_result", {}).get("summary")
                or state["input_text"]
            )
            sub_res = await rag_graph.ainvoke({"original_query": query, "attempts": 0})
            new_state_updates["rag_result"] = sub_res

        elif current_step == "draft":
            context = state.get("rag_result", {}).get("context", "")
            classification = state.get("classification_result", {})
            sub_res = await draft_graph.ainvoke(
                {
                    "source_document": state["input_text"],
                    "classification": classification,
                    "correspondence_type": _requested_correspondence_type(
                        classification
                    ),
                    "context": context,
                    "instructions": (
                        "Gelen evraka, evrakın amacı ve doğrulanmış bağlam doğrultusunda "
                        "resmi ve kurumsal bir Türkçe yanıt taslağı oluştur."
                    ),
                    "attempts": 0,
                }
            )
            new_state_updates["draft_result"] = sub_res

        elif current_step == "routing":
            draft = state.get("draft_result", {}).get("draft", "")
            score = state.get("draft_result", {}).get("confidence_score", 100.0)
            if state.get("draft_result", {}).get("requires_human_approval", False):
                score = 0.0
            sub_res = await routing_graph.ainvoke(
                {"draft": draft, "confidence_score": score}
            )
            new_state_updates["routing_result"] = sub_res

        else:
            logger.warning(f"Unknown workflow step skipped: {current_step}")

        # If this is the last step, compile final output
        if idx + 1 >= len(steps):
            class_res = new_state_updates.get("classification_result") or state.get(
                "classification_result"
            )
            rag_res = new_state_updates.get("rag_result") or state.get("rag_result")
            draft_res = new_state_updates.get("draft_result") or state.get(
                "draft_result"
            )
            routing_res = new_state_updates.get("routing_result") or state.get(
                "routing_result"
            )

            draft_status = (draft_res or {}).get("status")
            final_status = (
                draft_status
                if draft_status in {"FAILED", "NEEDS_HUMAN_APPROVAL"}
                else "COMPLETED"
            )
            new_state_updates["final_output"] = {
                "status": final_status,
                "classification": class_res,
                "rag": rag_res,
                "draft": draft_res,
                "routing": routing_res,
            }

        return new_state_updates

    # Routing Conditional Logic: Loops back to execute_step if steps remain, else goes to END
    def route_after_step(state: PlanningState) -> str:
        idx = state["current_step_idx"]
        steps = state["plan_steps"]

        if idx < len(steps):
            return "continue"
        return "end"

    # Define StateGraph
    builder = StateGraph(PlanningState)
    builder.add_node("planning", supervisor_planning_node)
    builder.add_node("executor", execute_step_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "executor")

    builder.add_conditional_edges(
        "executor",
        route_after_step,
        {
            "continue": "executor",
            "end": END,
        },
    )

    return builder.compile()
