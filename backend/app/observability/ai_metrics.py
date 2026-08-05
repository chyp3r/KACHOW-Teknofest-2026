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

from prometheus_client import Counter, Histogram, Info

from app.ai.policy import POLICY_VERSION

logger = logging.getLogger(__name__)

NODE_DURATION = Histogram(
    "kachow_node_duration_seconds",
    "Wall-clock duration of a single workflow node execution.",
    ["graph", "node", "status"],
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

#: The parameter set the deterministic decisions above were produced under.
#: Without it a shift in DRAFT_SCORE or CLAIM_MATCH is ambiguous between "the
#: traffic changed" and "we moved a threshold" -- and those call for opposite
#: responses. An Info rather than a label so it costs no cardinality.
POLICY_INFO = Info(
    "kachow_decision_policy",
    "Active version of the deterministic decision layer's parameter set.",
)
POLICY_INFO.info({"version": POLICY_VERSION})


def init_ai_metrics() -> None:
    """Force this module's import so its collectors register with Prometheus.

    ``Counter``/``Histogram`` register themselves with the default registry
    at definition time; this function exists only so ``main.py`` has an
    explicit, greppable call site symmetric with ``init_metrics(app)``,
    rather than relying on an import for its side effect.
    """
    logger.debug("AI metrics registered.")
