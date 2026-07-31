import logging
from typing import Any, Dict, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.router import RouterAgent
from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)


class RoutingState(TypedDict):
    """LangGraph State representing the routing workflow context."""

    draft: str
    confidence_score: float
    final_destination: str  # HR, Legal, Accounting, Citizen, HumanApproval
    justification: str


class RouteOutput(BaseModel):
    """Pydantic schema for structured routing decisions."""

    destination: Literal[
        "İnsan Kaynakları",
        "Hukuk Müşavirliği",
        "Mali İşler",
        "Vatandaş İlişkileri",
        "Bilgi İşlem Dairesi",
        "Destek Hizmetleri",
        "İnsan Onayı Gerekli"
    ] = Field(
        description="Yazının yönlendirileceği birim. Yalnızca tanımlı listeden bir birim seçilmelidir."
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu birime yönlendirildiğinin Türkçe gerekçesi."
    )


def create_routing_graph(llm_client: BaseLLMClient):
    """Create and compile the LangGraph document routing workflow.

    Flow: START -> Router Node -> END
    """
    router_agent = RouterAgent(llm_client)

    # 1. Routing Node
    async def routing_node(state: RoutingState) -> Dict[str, Any]:
        logger.info("Running Routing Node...")

        prompt = (
            f"Taslak İçeriği:\n\"\"\"\n{state['draft']}\n\"\"\"\n"
            f"Güven Skoru: {state.get('confidence_score', 100.0)}\n\n"
            "Bu yazının konusunu analiz ederek en uygun birime yönlendir.\n"
            "Birim adını Türkçe olarak yaz (örn. 'İnsan Kaynakları', 'Hukuk Müşavirliği', 'Mali İşler', 'Vatandaş İlişkileri').\n"
            "Güven skoru düşükse veya hassas bir durum varsa 'İnsan Onayı Gerekli' yönlendir.\n\n"
            "Yönlendirme kararını ve gerekçesini yapılandırılmış Türkçe formatta döndür."
        )

        try:
            # Fallback to HumanApproval if confidence score is critically low (< 50)
            if state.get("confidence_score", 100.0) < 50.0:
                logger.warning(
                    f"Confidence score too low ({state['confidence_score']}). Forcing HumanApproval route."
                )
                return {
                    "final_destination": "İnsan Onayı Gerekli",
                    "justification": "Yazı güven skoru kritik düzeyde düşük olduğu için insan onayına yönlendirildi.",
                    "routed_unit": "İnsan Onayı Gerekli",
                    "reasoning": "Yazı güven skoru kritik düzeyde düşük olduğu için insan onayına yönlendirildi.",
                    "priority": "Yüksek",
                }

            res: RouteOutput = await router_agent.run_structured(
                messages=prompt, response_model=RouteOutput
            )
            return {
                "final_destination": res.destination,
                "justification": res.justification,
                "routed_unit": res.destination,
                "reasoning": res.justification,
                "priority": "Yüksek" if res.destination == "İnsan Onayı Gerekli" else "Normal",
            }
        except Exception as e:
            logger.error(f"Routing Node failed: {e}", exc_info=True)
            return {
                "final_destination": "İnsan Onayı Gerekli",
                "justification": "Yönlendirme hatası nedeniyle insan onayına yönlendirildi.",
                "routed_unit": "İnsan Onayı Gerekli",
                "reasoning": "Yönlendirme hatası nedeniyle insan onayına yönlendirildi.",
                "priority": "Yüksek",
            }

    # Define Graph
    builder = StateGraph(RoutingState)
    builder.add_node("route", routing_node)

    builder.add_edge(START, "route")
    builder.add_edge("route", END)

    return builder.compile()
