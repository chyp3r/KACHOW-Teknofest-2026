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
    document_id: str | None
    plan_steps: list[str]  # e.g., ["classification", "rag", "draft", "routing"]
    current_step_idx: int
    classification_result: dict[str, Any]
    rag_result: dict[str, Any]
    draft_result: dict[str, Any]
    routing_result: dict[str, Any]
    chat_result: dict[str, Any]
    document_qa_result: dict[str, Any]
    final_output: dict[str, Any]


class PlanOutput(BaseModel):
    """Pydantic schema for structured planning decisions."""

    required_steps: list[str] = Field(
        description="Çalıştırılması gereken adımların sıralı listesi. Şunları içerebilir: 'classification', 'rag', 'draft', 'routing', 'chat', 'document_qa'."
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


from app.ai.agents.chat import ChatAgent
from app.ai.agents.document_qa import DocumentQAAgent
from app.ai.embeddings.models.openai_embeddings import OpenAIEmbeddingsClient
from app.infrastructure.vectorstore.base import BaseVectorStore

def create_planning_graph(
    llm_client: BaseLLMClient,
    document_analysis_graph: Any,
    rag_graph: Any,
    draft_graph: Any,
    routing_graph: Any,
    vector_store: BaseVectorStore | None = None,
    embeddings_client: BaseLLMClient | None = None,
):
    """Create and compile the LangGraph master Planning/Supervisor workflow.

    Evaluates the input query, generates an execution plan, and dynamically routes
    through sub-graphs (Classification, RAG, Draft, Routing) sequentially.
    """
    orchestrator_agent = OrchestratorAgent(llm_client)
    chat_agent = ChatAgent(llm_client)
    document_qa_agent = DocumentQAAgent(llm_client)

    # 1. Planning/Supervisor Node
    async def supervisor_planning_node(state: PlanningState) -> dict[str, Any]:
        logger.info("Supervisor planning task execution...")

        prompt = (
            f"Kullanıcı İsteği:\n\"\"\"\n{state['input_text']}\n\"\"\"\n"
            f"İlgili Belge ID (Eğer varsa):\n{state.get('document_id', 'Yok')}\n\n"
            "Bu istek için hangi iş süreçlerinin çalıştırılması gerektiğini belirle.\n"
            "İş Süreçleri Kuralları:\n"
            "- Eğer ham bir dosya/belge (PDF, görsel vb.) geldiyse önce 'classification' mutlaka çalışmalıdır.\n"
            "- Eğer belgeden bilgi çıkarma veya mevzuata dayalı cevaplama gerekiyorsa 'rag' çalışmalıdır.\n"
            "- Eğer resmi bir yazı, mektup veya taslak hazırlanması gerekiyorsa 'draft' çalışmalıdır.\n"
            "- Eğer hazırlanan yazının yönlendirilmesi/aksiyonu gerekiyorsa 'routing' çalışmalıdır.\n"
            "- Eğer kullanıcı spesifik bir 'Belge ID' vermişse ve YALNIZCA o belge içeriğiyle ilgili bir soru soruyorsa SADECE 'document_qa' çalıştırılmalıdır.\n"
            "- Eğer kullanıcı sadece sohbet ediyorsa veya bilgi dışı soru soruyorsa SADECE 'chat' yeterlidir.\n\n"
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
                "chat_result": {},
                "document_qa_result": {},
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
                "chat_result": {},
                "document_qa_result": {},
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
            sub_res = await document_analysis_graph.ainvoke(
                {"input_text": state["input_text"], "is_ocr_text": False}
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

        elif current_step == "chat":
            reply = await chat_agent.run(messages=state["input_text"])
            new_state_updates["chat_result"] = {"reply": reply, "status": "COMPLETED"}

        elif current_step == "document_qa":
            doc_id = state.get("document_id")
            if not doc_id or not vector_store or not embeddings_client:
                logger.error("Document QA failed: Missing document_id, vector_store, or embeddings_client.")
                new_state_updates["document_qa_result"] = {"reply": "Belge bulunamadı veya sistem yapılandırması eksik.", "status": "FAILED"}
            else:
                try:
                    # 1. Embed query
                    query_vector = await embeddings_client.embed_query(state["input_text"])
                    # 2. Search Qdrant with filter
                    filter_dict = {"storage_path": doc_id}
                    hits = await vector_store.similarity_search(
                        collection_name="document_qa",
                        query_vector=query_vector,
                        limit=3,
                        filter_dict=filter_dict,
                    )
                    
                    if not hits:
                        context = "Bu belgeye ait hiçbir içerik bulunamadı."
                    else:
                        context = "\n\n---\n\n".join([hit["text"] for hit in hits])
                        
                    # 3. Ask QA Agent
                    reply = await document_qa_agent._execute(
                        messages=[],
                        context=context,
                        query=state["input_text"]
                    )
                    new_state_updates["document_qa_result"] = {"reply": reply, "status": "COMPLETED"}
                except Exception as e:
                    logger.exception("Document QA step failed")
                    new_state_updates["document_qa_result"] = {"reply": f"Hata oluştu: {str(e)}", "status": "FAILED"}

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
            chat_res = new_state_updates.get("chat_result") or state.get(
                "chat_result"
            )
            document_qa_res = new_state_updates.get("document_qa_result") or state.get(
                "document_qa_result"
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
                "chat": chat_res,
                "document_qa": document_qa_res,
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
