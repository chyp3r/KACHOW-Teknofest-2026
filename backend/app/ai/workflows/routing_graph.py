import logging
from typing import Any, Dict, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.router import RouterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.events import emit_node_end, emit_node_start
from app.ai.workflows.resilience import LLM_RETRY, NODE_TIMEOUT_SECONDS, TRANSIENT_ERRORS, node_timeout

logger = logging.getLogger(__name__)

#: Below this score the draft is not trustworthy enough to route automatically.
HUMAN_APPROVAL_SCORE_THRESHOLD = 50.0

HUMAN_APPROVAL_UNIT = "İnsan Onayı Gerekli"

#: The routing target list. Kept as a module constant so the Literal below, the
#: prompt and any consumer cannot drift apart.
ROUTING_UNITS = (
    "İnsan Kaynakları",
    "Hukuk Müşavirliği",
    "Mali İşler",
    "Vatandaş İlişkileri",
    "Bilgi İşlem Dairesi",
    "Destek Hizmetleri",
    HUMAN_APPROVAL_UNIT,
)


class RoutingState(TypedDict, total=False):
    """LangGraph state for the unit-routing workflow.

    Declared with ``total=False`` and including every key the node writes.
    LangGraph drops updates for keys absent from the state schema, which is why
    ``routed_unit``/``reasoning``/``priority`` previously never reached the API
    response even though the node returned them.
    """

    draft: str
    confidence_score: float
    final_destination: str
    justification: str
    routed_unit: str
    reasoning: str
    priority: str


class RouteOutput(BaseModel):
    """Structured routing decision."""

    destination: Literal[
        "İnsan Kaynakları",
        "Hukuk Müşavirliği",
        "Mali İşler",
        "Vatandaş İlişkileri",
        "Bilgi İşlem Dairesi",
        "Destek Hizmetleri",
        "İnsan Onayı Gerekli",
    ] = Field(
        description="Yazının yönlendirileceği birim. Yalnızca tanımlı listeden bir birim seçilmelidir."
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu birime yönlendirildiğinin kısa Türkçe gerekçesi."
    )


def _decision(destination: str, justification: str) -> Dict[str, Any]:
    """Build the full routing state update for a decision.

    Args:
        destination: The chosen unit.
        justification: Turkish rationale.

    Returns:
        The state update, with both the canonical and the API-facing key names.
    """
    return {
        "final_destination": destination,
        "justification": justification,
        "routed_unit": destination,
        "reasoning": justification,
        "priority": "Yüksek" if destination == HUMAN_APPROVAL_UNIT else "Normal",
    }


def create_routing_graph(llm_client: BaseLLMClient):
    """Create and compile the unit-routing workflow.

    Flow: START -> route -> END

    Args:
        llm_client: LLM used for the routing decision. Pass the fast-tier client:
            the output is one label plus one sentence.

    Returns:
        The compiled LangGraph workflow.
    """
    router_agent = RouterAgent(llm_client)

    @node_timeout(NODE_TIMEOUT_SECONDS["route"])
    async def routing_node(state: RoutingState, config: RunnableConfig) -> Dict[str, Any]:
        logger.info("Running Routing Node...")
        await emit_node_start(
            config, "routing", "Birim Yönlendirme", "İlgili birim belirleniyor..."
        )

        score = state.get("confidence_score", 100.0)
        draft = (state.get("draft") or "").strip()

        if not draft:
            update = _decision(
                HUMAN_APPROVAL_UNIT,
                "Yönlendirilecek bir taslak bulunmadığı için insan onayına yönlendirildi.",
            )
        elif score < HUMAN_APPROVAL_SCORE_THRESHOLD:
            logger.warning("Confidence score %.1f too low; forcing human approval.", score)
            update = _decision(
                HUMAN_APPROVAL_UNIT,
                "Yazı güven skoru kritik düzeyde düşük olduğu için insan onayına yönlendirildi.",
            )
        else:
            prompt = (
                f'Taslak İçeriği:\n"""\n{draft}\n"""\n'
                f"Güven Skoru: {score}\n\n"
                "Bu yazının konusunu analiz ederek en uygun birime yönlendir.\n"
                f"Yalnızca şu birimlerden birini seç: {', '.join(ROUTING_UNITS)}.\n"
                "Hassas veya belirsiz bir durum varsa 'İnsan Onayı Gerekli' seç.\n\n"
                "Yönlendirme kararını ve kısa gerekçesini yapılandırılmış Türkçe formatta döndür."
            )
            try:
                res: RouteOutput = await router_agent.run_structured(
                    messages=prompt, response_model=RouteOutput, temperature=0.0
                )
                update = _decision(res.destination, res.justification)
            except TRANSIENT_ERRORS:
                logger.warning("Routing Node hit a transient error; retrying.")
                raise
            except Exception:
                logger.exception("Routing Node failed")
                update = _decision(
                    HUMAN_APPROVAL_UNIT,
                    "Yönlendirme hatası nedeniyle insan onayına yönlendirildi.",
                )

        await emit_node_end(
            config, "routing", "Birim Yönlendirme", "Birim yönlendirmesi tamamlandı.", update
        )
        return update

    builder = StateGraph(RoutingState)
    builder.add_node("route", routing_node, retry_policy=LLM_RETRY)
    builder.add_edge(START, "route")
    builder.add_edge("route", END)

    return builder.compile()
