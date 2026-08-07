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

from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.enums.user_role import UserRole

__all__ = [
    "BudgetPolicy",
    "GuardrailPolicy",
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
    """Margin thresholds for the lexical layer, and probability bands for the
    fused decision built on top of it.

    Attributes:
        presence_floor: Below this an intent is noise, not a candidate in the
            lexical layer's own scoring. Without a floor two rules scoring 0.1
            and 0.0 would read as a confident decision purely because nothing
            contested them. Still meaningful as a property of
            ``score_intents``'s output even though the top-level decision
            (see ``tau_high``/``tau_low`` below) no longer gates on it
            directly.
        decisive_margin: Reference lead for the lexical layer's own margin;
            same status as ``presence_floor`` above.
        compound_floor: Score at which both draft and analyze count as
            independently well-attested lexically, making the message a
            compound request. Checked on the raw additive lexical scores
            *before* fusion runs, deliberately -- a softmax's classes compete
            by construction, so it cannot represent "both readings are
            independently strong" the way an additive score can (see
            ``scripts/fit_router.py``'s module docstring).
        confidence_scale: Margin that maps to the lexical layer's own
            confidence in [0, 1] (``IntentScores.confidence``).
        tau_high: Minimum fused probability for the router to commit to an
            intent outright. Below it the ladder does not guess.
        tau_low: Below this fused probability there is no point asking a
            model either -- the evidence is too thin to be worth a round
            trip, so the ladder goes straight to a clarifying question.
            Between ``tau_low`` and ``tau_high`` is the band a fast-tier
            model call is reserved for (see
            ``app.ai.workflows.planner.classify_intent_with_model``).
    """

    presence_floor: float = 1.4
    decisive_margin: float = 1.2
    compound_floor: float = 2.6
    confidence_scale: float = 4.0
    tau_high: float = 0.55
    tau_low: float = 0.35


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

    Calibrated against ``evaluation/datasets/intents.jsonl`` with real
    nomic-embed-text vectors. The measurement is stark: correct decisions score
    0.859 and 0.880, while 0.747-0.758 is a coin flip (one correct, three wrong)
    and every genuinely under-specified message tops out at 0.740. The initial
    0.72 sat inside the noise band and produced three correct decisions against
    three wrong ones -- a layer that decides at random is worse than no layer,
    because the messages it gets wrong were previously escalating to a model
    that might have got them right.

    0.80 is the middle of the safe band (0.758 -> 0.859), not its edge. Picking
    the point that merely beats the last error would leave 0.002 of headroom on
    a fifteen-case sample.

    Attributes:
        decisive_similarity: Minimum cosine similarity to the winning class.
        decisive_margin: Minimum lead over the runner-up class. Not binding at
            the calibrated similarity -- both surviving decisions clear it
            comfortably (0.154, 0.098) -- but retained because two equally-good
            matches should not be separated by rounding.
    """

    decisive_similarity: float = 0.80
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
                "analyze": 140.0,
                "retrieve_mevzuat": 25.0,
                "suggest_mevzuat": 70.0,
                "route": 45.0,
                "writer": 180.0,
                "assist": 70.0,
                # Must comfortably exceed GUARDRAIL_JUDGE_TIMEOUT_SECONDS
                # (15.0s default): the node-level timeout has to lose the
                # race to the judge call's own internal timeout, or the
                # whole node gets cancelled mid-judge instead of the judge
                # gracefully degrading to None and the node finishing on the
                # deterministic result alone.
                "scan_sensitivity": 25.0,
            }
        )
    )
    workflow_ceiling_seconds: float = 480.0


@dataclass(frozen=True)
class GuardrailPolicy:
    """Thresholds and role mapping for the input/output guardrail layer.

    Attributes:
        sensitivity_block_levels: ``gizlilik_derecesi`` grades that force a
            document (or a draft built from it) to ``NEEDS_HUMAN_APPROVAL``
            instead of proceeding automatically -- the same routing a
            low-confidence draft already gets, not a separate mechanism.
        output_groundedness_threshold: Minimum share of an assist reply's
            extracted claims that must trace back to retrieved source
            material before ``output_gate`` lets it pass unredacted. Same
            concept as ``VerificationPolicy.min_automated_confidence``, scaled
            to a share rather than a 0-100 score because the assist path has
            no draft-quality score to reuse.
        pii_confidence_floor: Below this confidence a PII pattern match is
            treated as noise (logged, not flagged) rather than a finding --
            keeps an incidental 11-digit number from tripping TCKN handling
            on every partial match.
        judge_echo_overlap_threshold: Reuses
            ``VerificationPolicy.judge_echo_overlap_threshold``'s concept for
            the guardrail judge: above this token-overlap share with the
            content it was asked to judge, a verdict is an echo, not a
            judgement, and is discarded.
        role_clearance_map: The maximum ``SensitivityLevel`` each
            ``UserRole`` may read. Every ``UserRole`` member must have an
            entry -- an omitted role is not "no access", it is a role
            ``require_clearance`` cannot evaluate at all, which is a bug, not
            a restrictive default. ADMIN and MANAGER both map to the ceiling
            (a company manager is trusted with full access, same as an
            admin); EMPLOYEE's entry here is only the *default* a new
            employee starts at (``UserModel.clearance_level``'s own column
            default matches it) -- ``app.core.permissions.role_checker.
            clearance_for`` reads that per-user field for an EMPLOYEE
            rather than this map entry, since two employees can
            legitimately need different access.
    """

    sensitivity_block_levels: tuple[SensitivityLevel, ...] = (
        SensitivityLevel.GIZLI,
        SensitivityLevel.COK_GIZLI,
    )
    output_groundedness_threshold: float = 0.75
    pii_confidence_floor: float = 0.6
    judge_echo_overlap_threshold: float = 0.40
    role_clearance_map: Mapping[UserRole, SensitivityLevel] = field(
        default_factory=lambda: MappingProxyType(
            {
                UserRole.ADMIN: SensitivityLevel.COK_GIZLI,
                UserRole.MANAGER: SensitivityLevel.COK_GIZLI,
                UserRole.EMPLOYEE: SensitivityLevel.HIZMETE_OZEL,
            }
        )
    )


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
    guardrail: GuardrailPolicy = field(default_factory=GuardrailPolicy)

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

        for name, value in (
            ("intent.tau_high", self.intent.tau_high),
            ("intent.tau_low", self.intent.tau_low),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a probability in [0, 1]")

        if self.intent.tau_low >= self.intent.tau_high:
            raise ValueError(
                "intent.tau_low must stay below intent.tau_high -- otherwise the "
                "model-call band between them is empty or inverted"
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

        guardrail = self.guardrail
        for name, value in (
            ("guardrail.output_groundedness_threshold", guardrail.output_groundedness_threshold),
            ("guardrail.pii_confidence_floor", guardrail.pii_confidence_floor),
            ("guardrail.judge_echo_overlap_threshold", guardrail.judge_echo_overlap_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a share in [0, 1]")

        missing_roles = set(UserRole) - set(guardrail.role_clearance_map)
        if missing_roles:
            raise ValueError(
                "guardrail.role_clearance_map is missing entries for: "
                f"{sorted(role.value for role in missing_roles)}"
            )
