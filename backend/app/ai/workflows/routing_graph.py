import logging
from typing import Any, Dict, TypedDict

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

    destination: str = Field(
        description="Nihai aksiyon/departman. Şunlardan biri olmalıdır: 'HR', 'Legal', 'Accounting', 'Citizen', 'HumanApproval'."
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu departmana yönlendirildiğinin gerekçesi."
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
            "Bu yazının konusuna göre, yazıyı en uygun departmana veya aksiyona yönlendir.\n"
            "Desteklenen Hedefler:\n"
            "- 'HR': Personel, izin, işe alım, İnsan Kaynakları konuları.\n"
            "- 'Legal': Sözleşmeler, yasal süreçler, Hukuk konuları.\n"
            "- 'Accounting': Fatura, ödeme, maaş, Muhasebe konuları.\n"
            "- 'Citizen': Vatandaşa verilecek doğrudan cevaplar.\n"
            "- 'HumanApproval': Güven skoru düşükse veya çok hassas bir durum varsa insan onayına sunma.\n\n"
            "Lütfen yönlendirme kararını ve gerekçesini yapılandırılmış Türkçe formatta döndür."
        )

        try:
            # Fallback to HumanApproval if confidence score is critically low (< 50)
            if state.get("confidence_score", 100.0) < 50.0:
                logger.warning(
                    f"Confidence score too low ({state['confidence_score']}). Forcing HumanApproval route."
                )
                return {
                    "final_destination": "HumanApproval",
                    "justification": "Yazı güven skoru kritik düzeyde düşük olduğu için insan onayına yönlendirildi.",
                }

            res: RouteOutput = await router_agent.run_structured(
                messages=prompt, response_model=RouteOutput
            )
            return {
                "final_destination": res.destination,
                "justification": res.justification,
            }
        except Exception as e:
            logger.error(f"Routing Node failed: {e}", exc_info=True)
            return {
                "final_destination": "HumanApproval",
                "justification": "Yönlendirme hatası nedeniyle insan onayına yönlendirildi.",
            }

    # Define Graph
    builder = StateGraph(RoutingState)
    builder.add_node("route", routing_node)

    builder.add_edge(START, "route")
    builder.add_edge("route", END)

    return builder.compile()
