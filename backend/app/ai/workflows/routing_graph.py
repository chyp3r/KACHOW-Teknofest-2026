import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.router import RouterAgent
from app.ai.policy import get_policy
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.events import emit_node_end, emit_node_start
from app.ai.workflows.resilience import LLM_RETRY, TRANSIENT_ERRORS, node_timeout

logger = logging.getLogger(__name__)

#: Below this score the draft is not trustworthy enough to route automatically.
#: Policy owns it alongside `MIN_AUTOMATED_CONFIDENCE_SCORE`, whose relationship
#: to it is an enforced invariant: 70 is "may be sent without review", 50 is
#: "may not be routed at all", and inverting them would make a draft too weak to
#: route simultaneously good enough to send.
HUMAN_APPROVAL_SCORE_THRESHOLD = get_policy().routing.human_approval_score_threshold

#: `(name, description)` pairs for the units eligible for routing. Supplied by
#: the caller (see `create_routing_graph`) and re-fetched on every decision --
#: there is no module-level constant anymore, since the list is now
#: runtime-managed (see `app.domains.units`), not policy.
UnitsProvider = Callable[[], Awaitable[List[Tuple[str, str]]]]


class RoutingState(TypedDict, total=False):
    """LangGraph state for the unit-routing workflow.

    Declared with ``total=False`` and including every key the node writes.
    LangGraph drops updates for keys absent from the state schema, which is why
    ``routed_unit``/``reasoning``/``priority`` previously never reached the API
    response even though the node returned them.
    """

    draft: str
    confidence_score: float
    final_destination: Optional[str]
    justification: str
    routed_unit: Optional[str]
    reasoning: str
    priority: str
    requires_human_approval: bool


class RouteOutput(BaseModel):
    """Structured routing decision.

    ``destination`` is a plain ``str`` rather than a ``Literal`` -- the
    eligible unit set is runtime-managed and can change between two routing
    calls, so it cannot be baked into the response model's type. The caller
    (`routing_node` below) validates the value against the unit list that was
    actually offered in the prompt.
    """

    destination: str = Field(
        description="Yazının yönlendirileceği birim. Yalnızca verilen listeden bir birim seçilmelidir."
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu birime yönlendirildiğinin kısa Türkçe gerekçesi."
    )


def _decision(
    destination: Optional[str], justification: str, *, requires_human_approval: bool
) -> Dict[str, Any]:
    """Build the full routing state update for a decision.

    Args:
        destination: The chosen unit's name, or ``None`` when routing could
            not confidently assign one.
        justification: Turkish rationale.
        requires_human_approval: Whether a human must pick a unit instead --
            the same flag `app.domains.documents.draft_service` and the
            draft-quality gate use, not a special unit value.

    Returns:
        The state update, with both the canonical and the API-facing key names.
    """
    return {
        "final_destination": destination,
        "justification": justification,
        "routed_unit": destination,
        "reasoning": justification,
        "priority": "Yüksek" if requires_human_approval else "Normal",
        "requires_human_approval": requires_human_approval,
    }


def _format_units(units: List[Tuple[str, str]]) -> str:
    """Render `(name, description)` pairs as a Turkish bullet list for the prompt."""
    return "\n".join(f"- {name}: {description}" for name, description in units)


def create_routing_graph(llm_client: BaseLLMClient, units_provider: UnitsProvider):
    """Create and compile the unit-routing workflow.

    Flow: START -> route -> END

    Args:
        llm_client: LLM used for the routing decision. Pass the fast-tier client:
            the output is one label plus one sentence.
        units_provider: Async callable returning the currently active
            `(name, description)` units, read fresh on every call (see
            `app.domains.units.provider.get_active_units_for_routing`) --
            injected the same way `llm_client` is, so this module never
            imports `app.domains` directly.

    Returns:
        The compiled LangGraph workflow.
    """
    router_agent = RouterAgent(llm_client)

    @node_timeout("route")
    async def routing_node(state: RoutingState, config: RunnableConfig) -> Dict[str, Any]:
        logger.info("Running Routing Node...")
        await emit_node_start(
            config, "routing", "Birim Yönlendirme", "İlgili birim belirleniyor..."
        )

        score = state.get("confidence_score", 100.0)
        draft = (state.get("draft") or "").strip()
        units = await units_provider()

        if not units:
            logger.warning("No active units configured; routing cannot assign one.")
            update = _decision(
                None,
                "Tanımlı bir birim bulunmadığı için insan onayına yönlendirildi.",
                requires_human_approval=True,
            )
        elif not draft:
            update = _decision(
                None,
                "Yönlendirilecek bir taslak bulunmadığı için insan onayına yönlendirildi.",
                requires_human_approval=True,
            )
        elif score < HUMAN_APPROVAL_SCORE_THRESHOLD:
            logger.warning("Confidence score %.1f too low; forcing human approval.", score)
            update = _decision(
                None,
                "Yazı güven skoru kritik düzeyde düşük olduğu için insan onayına yönlendirildi.",
                requires_human_approval=True,
            )
        else:
            unit_names = {name for name, _ in units}
            prompt = (
                f'Taslak İçeriği:\n"""\n{draft}\n"""\n'
                f"Güven Skoru: {score}\n\n"
                "Bu yazının konusunu analiz ederek en uygun birime yönlendir.\n"
                f"Yönlendirme yapabileceğin birimler:\n{_format_units(units)}\n\n"
                "Yalnızca yukarıdaki listeden bir birim adı seç.\n\n"
                "Yönlendirme kararını ve kısa gerekçesini yapılandırılmış Türkçe formatta döndür."
            )
            try:
                res: RouteOutput = await router_agent.run_structured(
                    messages=prompt, response_model=RouteOutput, temperature=0.0
                )
                if res.destination in unit_names:
                    update = _decision(
                        res.destination, res.justification, requires_human_approval=False
                    )
                else:
                    logger.warning(
                        "Router returned a unit outside the offered list: %r", res.destination
                    )
                    update = _decision(
                        None,
                        "Model tanımlı birim listesi dışında bir yanıt verdi; insan onayına "
                        "yönlendirildi.",
                        requires_human_approval=True,
                    )
            except TRANSIENT_ERRORS:
                logger.warning("Routing Node hit a transient error; retrying.")
                raise
            except Exception:
                logger.exception("Routing Node failed")
                update = _decision(
                    None,
                    "Yönlendirme hatası nedeniyle insan onayına yönlendirildi.",
                    requires_human_approval=True,
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
