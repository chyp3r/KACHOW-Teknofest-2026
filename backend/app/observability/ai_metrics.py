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

from prometheus_client import Counter, Histogram

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


def init_ai_metrics() -> None:
    """Force this module's import so its collectors register with Prometheus.

    ``Counter``/``Histogram`` register themselves with the default registry
    at definition time; this function exists only so ``main.py`` has an
    explicit, greppable call site symmetric with ``init_metrics(app)``,
    rather than relying on an import for its side effect.
    """
    logger.debug("AI metrics registered.")
