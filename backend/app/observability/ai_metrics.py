"""AI-specific Prometheus collectors.

``prometheus-fastapi-instrumentator`` (see ``observability/metrics.py``) only
covers the HTTP layer -- request count/latency/status. Everything about the
AI pipeline's own behaviour (how long a draft's revision loop takes, how
often the judge degrades, how often a session hits the human-in-the-loop
gate) was previously invisible outside of log lines.

Scope note: ``NODE_DURATION`` and ``LLM_TOKENS`` are declared here for a
complete metric surface but are not wired up everywhere yet. Per-node timing
needs a start/end correlation that the current generic ``emit_node_start``/
``emit_node_end`` helpers don't carry (a node can legitimately emit
``node_start`` without a matching ``node_end`` under the same id, e.g. the
draft writer's completion is reported by the separate ``verify`` node), and
token counts aren't exposed by ``BaseLLMClient.generate()`` today. Wiring
either honestly requires touching the client abstraction or the per-node
call sites individually rather than one shared choke point; left as declared
but unpopulated rather than instrumented with fabricated numbers.
"""

import logging

from prometheus_client import Counter, Gauge, Histogram, Info

from app.ai.policy import POLICY_VERSION

logger = logging.getLogger(__name__)

NODE_DURATION = Histogram(
    "kachow_node_duration_seconds",
    "Wall-clock duration of a single workflow node execution.",
    ["graph", "node", "status"],
    # prometheus_client's own default buckets top out at 10.0s -- far too
    # coarse for this metric's actual subjects: BudgetPolicy.node_seconds
    # ranges from 25s to 180s, and workflow_ceiling_seconds is 480s. Every
    # real observation was silently collapsing into the +Inf bucket,
    # discovered running evaluation/latency/budget_report.py (Workstream
    # E3) against a live analyze run -- p50/p95/p99 all read back as the
    # same floor value (10.0) regardless of the true duration. Spans from
    # sub-second (the fastest node, retrieve_mevzuat, ~12ms) past the
    # workflow ceiling, with enough resolution in the 25-180s band the
    # actual budgets live in to make a p95-vs-budget comparison meaningful.
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0, 180.0, 240.0, 300.0, 480.0),
)

LLM_DURATION = Histogram(
    "kachow_llm_call_duration_seconds",
    "Wall-clock duration of a single BaseAgent call.",
    ["agent", "method"],
)

LLM_TOKENS = Counter(
    "kachow_llm_tokens_total",
    "Tokens generated per agent call, by kind.",
    ["agent", "kind"],
)

DRAFT_SCORE = Histogram(
    "kachow_draft_confidence_score",
    "Draft quality score at verification time.",
    ["source"],
    buckets=(0, 20, 40, 60, 70, 80, 90, 100),
)

DRAFT_REVISIONS = Counter(
    "kachow_draft_revisions_total",
    "Draft reflexion-loop revisions triggered, by cause.",
    ["trigger"],
)

JUDGE_FAILURES = Counter(
    "kachow_judge_failures_total",
    "LLM judge calls that degraded instead of returning a verdict.",
    ["reason"],
)

#: Same role as JUDGE_FAILURES, kept separate rather than an added label:
#: the guardrail judge (app.ai.guardrails.llm_nuance) degrading means "this
#: decision fell back to the deterministic-only verdict," a security-relevant
#: event worth its own signal rather than being folded into draft-quality
#: judge failures.
GUARDRAIL_JUDGE_FAILURES = Counter(
    "kachow_guardrail_judge_failures_total",
    "Guardrail nuance-layer LLM judge calls that degraded to deterministic-only.",
    ["reason"],
)

#: The guardrail system's overall decision surface -- every stage (input at
#: upload, output at response time) and every kind (pii, sensitivity,
#: injection, magic_byte, archive_bomb, groundedness, leakage, llm_judge),
#: not just the judge layer's own failures (GUARDRAIL_JUDGE_FAILURES above).
#: Incremented from a single choke point (app.observability.guardrail_recorder
#: .record_event) rather than at each of its three call sites, so this stays
#: accurate as new guardrail checks are added without a matching metrics edit.
GUARDRAIL_DECISIONS = Counter(
    "kachow_guardrail_decisions_total",
    "Guardrail decisions made, by stage, kind, and outcome.",
    ["stage", "kind", "decision"],
)

HITL_INTERRUPTS = Counter(
    "kachow_hitl_interrupts_total",
    "Human-in-the-loop interrupts raised, by kind.",
    ["kind"],
)

HITL_RESUMES = Counter(
    "kachow_hitl_resume_total",
    "Human-in-the-loop resume calls received, by action.",
    ["action"],
)

STRUCT_RETRIES = Counter(
    "kachow_structured_retry_total",
    "Structured-output retries beyond the first attempt, by agent.",
    ["agent"],
)

EXTRACTION = Counter(
    "kachow_extraction_total",
    "Document text extraction attempts, by extractor and outcome.",
    ["extractor", "outcome"],
)

#: The deterministic draft gate's own behaviour, which was previously invisible:
#: DRAFT_SCORE records the number it produced but nothing recorded *how*. The
#: `method` label is the escalation ladder in `draft_verifier._support_for`
#: (exact -> canonical -> token_overlap -> none), so a rise in `none` for one
#: kind localises a groundedness regression to a single claim type, and the
#: `canonical` share measures how much work type-aware normalisation is doing.
#: Both labels are closed sets -- no free text, which would blow up cardinality.
CLAIM_MATCH = Counter(
    "kachow_claim_match_total",
    "Draft claims checked against source material, by claim kind and match method.",
    ["kind", "method"],
)

#: Whether the intent ladder's semantic rung (app.ai.semantic.prototype_matcher)
#: is actually loaded, as opposed to having silently disabled itself because
#: the on-disk vector file was stale (built under a different embedding model
#: or a different POLICY_VERSION) or missing outright. Layer 2 disabling
#: itself is the *correct* behaviour -- deciding from stale vectors is worse
#: than paying for a model call -- but it must not be silent: every message
#: the lexical layer abstains on then skips straight to the clarify/guess
#: fallback instead of getting a semantic second opinion. Set once at graph
#: construction time (see planning_graph.py's PrototypeMatcher setup), not
#: per-request, so this is a Gauge rather than a Counter.
ROUTER_SEMANTIC_AVAILABLE = Gauge(
    "kachow_router_semantic_available",
    "Whether the intent ladder's semantic prototype layer loaded successfully (1) or disabled itself (0).",
)

#: Every router decision, by resolved intent and by the mechanism that
#: produced it (``fused``/``fused_semantic``/``compound``/
#: ``clarification_resolved``/``model``/``model_failed``/``clarify`` -- see
#: ``app.ai.workflows.planner.PlanDecision.source``). This is the number that
#: was previously invisible outside of a `run_recorder` DB row: how often
#: production actually asks a clarifying question, and which rung is doing
#: the deciding.
ROUTER_DECISIONS = Counter(
    "kachow_router_decisions_total",
    "Router decisions, by resolved intent and by the mechanism that produced them.",
    ["intent", "source"],
)

#: Distribution of `PlanDecision.confidence`, by source. Comparable across
#: every source since the fusion rewrite gave them a single calibrated scale
#: (see `PlanDecision.confidence`'s docstring) -- before that, three
#: incompatible scales landing in the same histogram would have been
#: meaningless.
ROUTER_CONFIDENCE = Histogram(
    "kachow_router_confidence",
    "Router decision confidence in [0, 1], by source.",
    ["source"],
    buckets=(0.0, 0.2, 0.35, 0.5, 0.55, 0.7, 0.85, 0.95, 1.0),
)

#: Wall-clock cost of each stage `resolve_plan` can pay for, so the semantic
#: rung coming back online (see `ROUTER_SEMANTIC_AVAILABLE`) has a number
#: attached to the latency it adds, and the (currently empty on the gold set,
#: see `evaluation/harness/intent_suite.py::run_with_model`) model band's
#: real-traffic cost is visible once it does fire.
ROUTER_STAGE_DURATION = Histogram(
    "kachow_router_stage_duration_seconds",
    "Wall-clock duration of one router decision stage.",
    ["stage"],
)

#: Every time a turn that resolved to "assist" got handed off to draft/revise
#: instead of actually running the assist step (Faz 7, see
#: planning_graph._step_assist) -- by "reason" (``fallback_source``: a
#: deterministic re-score caught it before assist ever ran, because the
#: routing decision itself came from a fallback source with no real
#: evidence behind it; ``model_tool``: the assistant model itself called
#: ``request_handoff`` mid-turn) and by the "target" it moved to. A rising
#: rate here is a signal the fusion weights (app.ai.policy.router_weights)
#: have gone stale for current traffic, not that this fix is failing --
#: this fix is the *symptom detector* for that drift, not its cure.
ROUTER_ASSIST_HANDOFFS = Counter(
    "kachow_router_assist_handoffs_total",
    "Turns routed to assist that were handed off to draft/revise instead, by reason and target.",
    ["reason", "target"],
)

#: How the human approval gate's "revizyon iste" loop (planning_graph
#: gate_revise_node/route_after_gate) resolves: another round produced (still
#: within HITL_MAX_GATE_REVISIONS) vs. the round cap was hit and the gate
#: stopped offering it. Distinguishes "users keep revising and it works" from
#: "users keep hitting the cap," which call for different responses (better
#: rewrites vs. a higher cap).
GATE_REVISIONS = Counter(
    "kachow_gate_revisions_total",
    "Human approval gate revision rounds, by outcome.",
    ["outcome"],
)

#: Findings from app.ai.revision.conflict -- a user's revision instruction
#: applied despite contradicting the retrieved mevzuat or the source
#: document. Every finding is applied anyway and only forces a human gate
#: (see ConflictReport.applied_anyway); this metric is what makes "how often
#: does that actually happen, and of what kind" visible instead of only
#: showing up as an extra HITL_INTERRUPTS count with no context.
REVISION_CONFLICTS = Counter(
    "kachow_revision_conflicts_total",
    "Instruction-vs-mevzuat/source conflicts detected during a revision, by kind, severity and source.",
    ["kind", "severity", "source"],
)

#: Whether a revision's conditional legislation re-retrieval
#: (app.ai.revision.retrieval.maybe_extend_context) actually ran, by outcome
#: -- most revisions should skip (pure tone/length edits), so a rising
#: "extended" share tracks how often users ask revisions to introduce new
#: normative content, and "failed" tracks retriever health independent of
#: the draft's own quality gate.
REVISION_RETRIEVAL = Counter(
    "kachow_revision_retrieval_total",
    "Revision-time conditional legislation re-retrieval outcomes.",
    ["decision"],
)

#: The parameter set the deterministic decisions above were produced under.
#: Without it a shift in DRAFT_SCORE or CLAIM_MATCH is ambiguous between "the
#: traffic changed" and "we moved a threshold" -- and those call for opposite
#: responses. An Info rather than a label so it costs no cardinality.
POLICY_INFO = Info(
    "kachow_decision_policy",
    "Active version of the deterministic decision layer's parameter set.",
)
POLICY_INFO.info({"version": POLICY_VERSION})


def router_semantic_available() -> bool:
    """Read ``ROUTER_SEMANTIC_AVAILABLE`` back, for the ``/system/health?deep`` probe.

    ``prometheus_client`` gauges have no public getter; ``_value`` is the
    documented escape hatch other instrumentation code uses for exactly this
    "read my own gauge back" case, rather than tracking the state twice.
    """
    return bool(ROUTER_SEMANTIC_AVAILABLE._value.get())


def init_ai_metrics() -> None:
    """Force this module's import so its collectors register with Prometheus.

    ``Counter``/``Histogram`` register themselves with the default registry
    at definition time; this function exists only so ``main.py`` has an
    explicit, greppable call site symmetric with ``init_metrics(app)``,
    rather than relying on an import for its side effect.
    """
    logger.debug("AI metrics registered.")
