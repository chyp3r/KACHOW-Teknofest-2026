import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.router import RouterAgent
from app.ai.policy import get_policy
from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.events import emit_node_end, emit_node_start
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.resilience import LLM_RETRY, TRANSIENT_ERRORS, node_timeout

logger = logging.getLogger(__name__)

#: Below this score the draft is not trustworthy enough to route automatically
#: via the model call -- routing still always proposes a best-effort unit
#: (see `_best_effort_unit`), just flagged `requires_human_approval=True`
#: for audit rather than left blank. Policy owns it alongside
#: `MIN_AUTOMATED_CONFIDENCE_SCORE`, whose relationship to it is an enforced
#: invariant: 70 is "may be sent without review", 50 is "not confident
#: enough to route automatically", and inverting them would make a draft too
#: weak to route simultaneously good enough to send.
HUMAN_APPROVAL_SCORE_THRESHOLD = get_policy().routing.human_approval_score_threshold

#: `(name, description)` pairs for the units eligible for routing, scoped to
#: one company. Supplied by the caller (see `create_routing_graph`) and
#: re-fetched on every decision -- there is no module-level constant
#: anymore, since the list is now runtime-managed (see `app.domains.units`),
#: not policy. Takes `company_id` because units are company-scoped (Faz 1
#: tenancy work): returning every company's units here would leak one
#: tenant's department names/descriptions into another's routing prompt.
UnitsProvider = Callable[[str], Awaitable[List[Tuple[str, str]]]]


class RoutingState(TypedDict, total=False):
    """LangGraph state for the unit-routing workflow.

    Declared with ``total=False`` and including every key the node writes.
    LangGraph drops updates for keys absent from the state schema, which is why
    ``routed_unit``/``reasoning``/``priority`` previously never reached the API
    response even though the node returned them.
    """

    draft: str
    confidence_score: float
    #: Which company's unit list to route against. Every caller supplies it
    #: now (`DraftService.generate_draft_and_route`, `routing/router.py`,
    #: and `PlanningState.company_id` via `planning_graph.py`'s routing
    #: sub-call) -- empty/missing still degrades to "no units configured"
    #: (see `routing_node`'s `if not units:` branch) rather than falling
    #: back to every company's units, fail-secure for any caller this
    #: doesn't hold for.
    company_id: str
    final_destination: Optional[str]
    justification: str
    routed_unit: Optional[str]
    reasoning: str
    priority: str
    requires_human_approval: bool
    #: Second-choice unit name(s), when a runner-up could be determined --
    #: never a substitute for `routed_unit`, only ever an option shown
    #: alongside it (see Görev's "her zaman bir öneri + alternatif"
    #: requirement). Empty when the company has only one active unit.
    alternative_units: List[str]


class RouteOutput(BaseModel):
    """Structured routing decision.

    ``destination``/``alternative`` are plain ``str`` rather than a
    ``Literal`` -- the eligible unit set is runtime-managed and can change
    between two routing calls, so it cannot be baked into the response
    model's type. The caller (`routing_node` below) validates both against
    the unit list that was actually offered in the prompt.
    """

    destination: str = Field(
        description="Yazının yönlendirileceği birim. Yalnızca verilen listeden bir birim seçilmelidir."
    )
    alternative: str = Field(
        default="",
        description=(
            "Birincil öneri uygun bulunmazsa denenebilecek ikinci en uygun birim. "
            "Yalnızca verilen listeden, birincil öneriyle aynı olmayan bir birim adı. "
            "Uygun bir alternatif yoksa boş bırak."
        ),
    )
    justification: str = Field(
        description="Yazının içeriğine göre neden bu birime yönlendirildiğinin kısa Türkçe gerekçesi."
    )


def _decision(
    destination: Optional[str],
    justification: str,
    *,
    requires_human_approval: bool,
    alternatives: Tuple[str, ...] = (),
) -> Dict[str, Any]:
    """Build the full routing state update for a decision.

    Args:
        destination: The chosen unit's name, or ``None`` only when the
            company has no active units at all -- every other case fills
            this from ``_best_effort_unit`` rather than leaving it unset
            (see that function's own docstring).
        justification: Turkish rationale.
        requires_human_approval: Whether this pick is low-confidence enough
            to flag for review -- the same flag
            `app.domains.documents.draft_service` and the draft-quality
            score use for scoring/audit. Recorded, but never itself a
            reason to withhold `destination`: a unit suggestion is always
            better than none (see Görev's own requirement).
        alternatives: Runner-up unit name(s), if any.

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
        "alternative_units": list(alternatives),
    }


def _format_units(units: List[Tuple[str, str]]) -> str:
    """Render `(name, description)` pairs as a Turkish bullet list for the prompt."""
    return "\n".join(f"- {name}: {description}" for name, description in units)


def _tokenize(text: str) -> set[str]:
    """Fold text to its significant (length > 2) normalized tokens."""
    return {token for token in normalize(text).split() if len(token) > 2}


def _rank_units(draft: str, units: List[Tuple[str, str]]) -> List[str]:
    """Every unit's name, ranked by how much of the draft's own vocabulary
    its name+description shares -- highest overlap first.

    A deliberately weak, deterministic signal (plain token overlap, not a
    semantic match) rather than no signal at all: when nothing overlaps
    (an empty draft, unrelated vocabulary), every unit scores 0 and
    Python's stable sort leaves them in the caller's own order, so this
    still returns *something* usable rather than an arbitrary shuffle.

    Args:
        draft: The draft text to score units against (may be empty).
        units: `(name, description)` pairs.

    Returns:
        Unit names, best match first. Same length as `units`.
    """
    draft_tokens = _tokenize(draft)
    return [
        name
        for name, _description in sorted(
            units,
            key=lambda unit: len(draft_tokens & _tokenize(f"{unit[0]} {unit[1]}")),
            reverse=True,
        )
    ]


def _best_effort_unit(draft: str, units: List[Tuple[str, str]]) -> Tuple[str, Tuple[str, ...]]:
    """A primary + (up to one) alternative unit, guaranteed non-empty when
    `units` is non-empty.

    The deterministic fallback every branch that used to leave
    `routed_unit` unset now calls instead: whether the model failed,
    returned something off-list, or was never confident enough to ask
    (`score < HUMAN_APPROVAL_SCORE_THRESHOLD`), the company's own unit list
    is never empty-handed to the user (see Görev's "her zaman en az bir
    öneri" requirement) -- a plausible guess beats an unfilled field, and
    the caller-visible `requires_human_approval` flag still records that
    this specific pick was a fallback, for audit.

    Args:
        draft: The draft text to score against (may be empty).
        units: This company's active `(name, description)` units. Must be
            non-empty -- the "no units configured at all" case is handled
            by the caller before this is ever reached.

    Returns:
        The top-ranked unit name, and a 0-or-1-length tuple with the
        runner-up when one exists.
    """
    ranking = _rank_units(draft, units)
    return ranking[0], tuple(ranking[1:2])


def _fill_alternative(
    draft: str, units: List[Tuple[str, str]], primary: str, candidate: str
) -> Tuple[str, ...]:
    """Resolve this decision's alternative: the model's own pick if valid,
    else a deterministic best-effort runner-up excluding `primary`.

    Args:
        draft: The draft text (for the deterministic fallback ranking).
        units: This company's active units.
        primary: The already-decided primary destination.
        candidate: The model's own `RouteOutput.alternative`, possibly
            invalid (off-list, blank, or a duplicate of `primary`).

    Returns:
        A 0-or-1-length tuple.
    """
    unit_names = {name for name, _ in units}
    if candidate and candidate != primary and candidate in unit_names:
        return (candidate,)
    remaining = [unit for unit in units if unit[0] != primary]
    if not remaining:
        return ()
    return tuple(_rank_units(draft, remaining)[:1])


def create_routing_graph(llm_client: BaseLLMClient, units_provider: UnitsProvider):
    """Create and compile the unit-routing workflow.

    Flow: START -> route -> END

    Args:
        llm_client: LLM used for the routing decision. Pass the fast-tier client:
            the output is one label plus one sentence.
        units_provider: Async callable taking a `company_id` and returning
            that company's currently active `(name, description)` units,
            read fresh on every call (see
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
        company_id = state.get("company_id") or ""
        units = await units_provider(company_id) if company_id else []

        if not units:
            # The one branch that genuinely has nothing to suggest -- every
            # other case below always fills `destination` from
            # `_best_effort_unit` instead of leaving it unset (see Görev's
            # "her zaman en az bir öneri" requirement).
            logger.warning("No active units configured; routing cannot assign one.")
            update = _decision(
                None,
                "Şirkette tanımlı aktif birim bulunmuyor.",
                requires_human_approval=True,
            )
        elif not draft:
            primary, alternatives = _best_effort_unit(draft, units)
            update = _decision(
                primary,
                "Yönlendirilecek bir taslak metni bulunmadığı için birim, şirketin birim "
                "listesinden en olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                requires_human_approval=True,
                alternatives=alternatives,
            )
        elif score < HUMAN_APPROVAL_SCORE_THRESHOLD:
            logger.warning("Confidence score %.1f too low; falling back to a best-effort pick.", score)
            primary, alternatives = _best_effort_unit(draft, units)
            update = _decision(
                primary,
                "Yazının güven skoru düşük olduğu için birim, taslağın içeriğine göre en "
                "olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                requires_human_approval=True,
                alternatives=alternatives,
            )
        else:
            unit_names = {name for name, _ in units}
            prompt = (
                f'Taslak İçeriği:\n"""\n{draft}\n"""\n'
                f"Güven Skoru: {score}\n\n"
                "Bu yazının konusunu analiz ederek en uygun birime yönlendir. Mümkünse "
                "ikinci en uygun birimi de alternatif olarak belirt.\n"
                f"Yönlendirme yapabileceğin birimler:\n{_format_units(units)}\n\n"
                "Yalnızca yukarıdaki listeden bir birim adı seç.\n\n"
                "Yönlendirme kararını ve kısa gerekçesini yapılandırılmış Türkçe formatta döndür."
            )
            try:
                res: RouteOutput = await router_agent.run_structured(
                    messages=prompt, response_model=RouteOutput, temperature=0.0
                )
                if res.destination in unit_names:
                    alternatives = _fill_alternative(draft, units, res.destination, res.alternative)
                    update = _decision(
                        res.destination,
                        res.justification,
                        requires_human_approval=False,
                        alternatives=alternatives,
                    )
                else:
                    logger.warning(
                        "Router returned a unit outside the offered list: %r", res.destination
                    )
                    primary, alternatives = _best_effort_unit(draft, units)
                    update = _decision(
                        primary,
                        "Model tanımlı birim listesi dışında bir yanıt verdi; birim, taslağın "
                        "içeriğine göre en olası seçenek olarak önerildi; gözden geçirilmesi "
                        "önerilir.",
                        requires_human_approval=True,
                        alternatives=alternatives,
                    )
            except TRANSIENT_ERRORS:
                logger.warning("Routing Node hit a transient error; retrying.")
                raise
            except Exception:
                logger.exception("Routing Node failed")
                primary, alternatives = _best_effort_unit(draft, units)
                update = _decision(
                    primary,
                    "Yönlendirme sırasında bir hata oluştu; birim, taslağın içeriğine göre en "
                    "olası seçenek olarak önerildi; gözden geçirilmesi önerilir.",
                    requires_human_approval=True,
                    alternatives=alternatives,
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
