"""Typed, versioned parameters for the deterministic decision layer.

Every threshold the non-LLM decision layer acts on used to live next to the code
that read it: ``70.0`` in ``draft_verifier``, ``50.0`` in ``routing_graph``,
``0.6/0.4`` in ``llm_judge``, ``12`` and ``40`` and ``4`` in ``planning_graph``.
Individually reasonable, collectively unreviewable -- two of them are the *same*
concept ("does this need a human?") with no stated relationship, and one table
had entries nothing read at all.

Why frozen dataclasses rather than YAML
---------------------------------------
A configuration file buys the ability to change a threshold without changing
code, which is precisely what is *not* wanted here. These numbers are
calibrated against ``evaluation/datasets``; moving one should require a
CHANGELOG entry and an eval run, not a redeploy. Typed dataclasses give the
invariants below somewhere to live, mypy and the IDE work on them for free, and
there is no parse path where production and tests can drift apart.

The invariants are the real product of this module. They encode relationships
that were previously only true by coincidence -- nothing stopped someone raising
the routing threshold above the automation threshold and inverting the gate.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

__all__ = [
    "BudgetPolicy",
    "IntentPolicy",
    "MemoryPolicy",
    "Policy",
    "SemanticPolicy",
    "RoutingPolicy",
    "VerificationPolicy",
]


@dataclass(frozen=True)
class VerificationPolicy:
    """Thresholds and weights for the deterministic draft gate.

    Attributes:
        min_automated_confidence: At or above this a draft may be sent without
            a human. The upper of the two human-approval thresholds.
        unsupported_claim_penalty: Points deducted per ungrounded claim.
        max_unsupported_penalty: Ceiling on that deduction, so a draft with many
            small issues still scores above one that is structurally broken --
            the two failure modes must not collapse onto the same number.
        token_overlap_threshold: Share of a value's significant tokens that must
            appear in the sources for the tolerant fallback to accept it.
        judge_deterministic_weight: Weight of the deterministic score in the
            hybrid verdict.
        judge_model_weight: Weight of the judge's score. Must complete the
            deterministic weight to 1.0.
        judge_echo_overlap_threshold: Above this share of a verdict's own tokens
            appearing in the draft, the verdict is an echo rather than a
            judgement and is discarded.
    """

    min_automated_confidence: float = 70.0
    unsupported_claim_penalty: float = 12.0
    max_unsupported_penalty: float = 60.0
    token_overlap_threshold: float = 0.75
    judge_deterministic_weight: float = 0.6
    judge_model_weight: float = 0.4
    judge_echo_overlap_threshold: float = 0.40


@dataclass(frozen=True)
class RoutingPolicy:
    """The unit list and the score below which nothing may be routed.

    Attributes:
        human_approval_score_threshold: Below this a draft is not trustworthy
            enough to route anywhere but a human. The *lower* of the two
            thresholds -- see :func:`Policy.check_invariants` for why the
            relationship matters.
        units: The routing targets. Single source of truth; the ``Literal`` in
            ``routing_graph.RouteOutput`` is checked against it by test.
        human_approval_unit: The escape hatch inside ``units``.
    """

    human_approval_score_threshold: float = 50.0
    human_approval_unit: str = "İnsan Onayı Gerekli"
    units: tuple[str, ...] = (
        "İnsan Kaynakları",
        "Hukuk Müşavirliği",
        "Mali İşler",
        "Vatandaş İlişkileri",
        "Bilgi İşlem Dairesi",
        "Destek Hizmetleri",
        "İnsan Onayı Gerekli",
    )


@dataclass(frozen=True)
class IntentPolicy:
    """Margin thresholds for the scored intent resolver.

    Attributes:
        presence_floor: Below this an intent is noise, not a candidate. Without
            a floor two rules scoring 0.1 and 0.0 would read as a confident
            decision purely because nothing contested them.
        decisive_margin: Lead the top intent needs over the runner-up to be
            acted on. Below it the resolver abstains.
        compound_floor: Score at which both draft and analyze count as
            independently well-attested, making the message a compound request.
        confidence_scale: Margin that maps to full confidence.
    """

    presence_floor: float = 1.4
    decisive_margin: float = 1.2
    compound_floor: float = 2.6
    confidence_scale: float = 4.0


@dataclass(frozen=True)
class MemoryPolicy:
    """Conversation-history retention bounds.

    Attributes:
        history_window: Turns kept verbatim in the prompt each turn.
        history_raw_cap: Raw turns retained in state before consolidation must
            have folded them into the summary. Must exceed ``history_window``
            so consolidation always has the overflow available.
        consolidation_batch_size: Minimum newly-overflowed turns worth a model
            call.
        qa_result_limit: Passages retrieved for document Q&A.
    """

    history_window: int = 12
    history_raw_cap: int = 40
    consolidation_batch_size: int = 4
    qa_result_limit: int = 4


@dataclass(frozen=True)
class SemanticPolicy:
    """Thresholds for the embedding-based prototype layer.

    Both must be cleared for a semantic match to be acted on. Cosine similarity
    between short Turkish sentences is compressed -- unrelated official-register
    sentences routinely sit around 0.6 -- so an absolute threshold alone fires
    constantly, while a margin alone fires on two equally-poor matches that
    happen to differ.

    Attributes:
        decisive_similarity: Minimum cosine similarity to the winning class.
        decisive_margin: Minimum lead over the runner-up class.
    """

    decisive_similarity: float = 0.72
    decisive_margin: float = 0.04


@dataclass(frozen=True)
class BudgetPolicy:
    """Per-node time budgets at the balanced reasoning level.

    Attributes:
        node_seconds: Node name -> budget. Every key must be consumed by a node
            somewhere; a dead entry is a budget someone believes is enforced and
            is not.
        workflow_ceiling_seconds: The whole-workflow timeout no scaled node
            budget may exceed.
    """

    node_seconds: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType(
            {
                "analyze": 90.0,
                "retrieve_mevzuat": 15.0,
                "suggest_mevzuat": 45.0,
                "route": 30.0,
                "writer": 120.0,
            }
        )
    )
    workflow_ceiling_seconds: float = 300.0


@dataclass(frozen=True)
class Policy:
    """The complete parameter surface of the deterministic decision layer."""

    version: str
    verification: VerificationPolicy = field(default_factory=VerificationPolicy)
    routing: RoutingPolicy = field(default_factory=RoutingPolicy)
    intent: IntentPolicy = field(default_factory=IntentPolicy)
    memory: MemoryPolicy = field(default_factory=MemoryPolicy)
    semantic: SemanticPolicy = field(default_factory=SemanticPolicy)
    budget: BudgetPolicy = field(default_factory=BudgetPolicy)

    def check_invariants(self) -> None:
        """Assert the relationships between parameters that must always hold.

        Called at import time, so a policy that contradicts itself fails the
        process rather than producing quietly wrong decisions in production.

        Raises:
            ValueError: When any invariant is violated.
        """
        verification = self.verification
        routing = self.routing

        # The two human-approval thresholds are the same concept at different
        # severities: 70 is "may be sent without review", 50 is "may not be
        # routed at all". Inverting them would make a draft too weak to route
        # simultaneously good enough to send.
        if routing.human_approval_score_threshold >= verification.min_automated_confidence:
            raise ValueError(
                "routing.human_approval_score_threshold must stay below "
                "verification.min_automated_confidence"
            )

        if abs(
            verification.judge_deterministic_weight + verification.judge_model_weight - 1.0
        ) > 1e-9:
            raise ValueError("judge blend weights must sum to 1.0")

        for name, value in (
            ("token_overlap_threshold", verification.token_overlap_threshold),
            ("judge_echo_overlap_threshold", verification.judge_echo_overlap_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        for name, value in (
            ("semantic.decisive_similarity", self.semantic.decisive_similarity),
            ("semantic.decisive_margin", self.semantic.decisive_margin),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        if self.intent.compound_floor < self.intent.presence_floor:
            raise ValueError(
                "intent.compound_floor must be at least intent.presence_floor -- a "
                "compound reading cannot need less evidence than a single one"
            )

        if self.memory.history_raw_cap <= self.memory.history_window:
            raise ValueError(
                "memory.history_raw_cap must exceed memory.history_window so "
                "consolidation always has overflow to fold in"
            )

        ceiling = self.budget.workflow_ceiling_seconds
        for node, seconds in self.budget.node_seconds.items():
            if seconds <= 0:
                raise ValueError(f"budget for node {node!r} must be positive")
            if seconds > ceiling:
                raise ValueError(
                    f"budget for node {node!r} ({seconds}s) exceeds the workflow "
                    f"ceiling ({ceiling}s)"
                )

        if routing.human_approval_unit not in routing.units:
            raise ValueError("routing.human_approval_unit must be one of routing.units")
