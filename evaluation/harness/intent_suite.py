"""Measures the full intent decision against the intent gold set.

Binds to :func:`app.ai.workflows.planner.resolve_plan` with ``llm_client=None``
-- lexical evidence, the compound check and the semantic rung all run for
real; only the fast-tier model call is skipped. That keeps ``make eval`` fully
offline and reproducible (no model call, no non-determinism) while measuring
what production actually runs: an earlier version of this suite called the
lexical-only decision function directly, which meant the semantic rung, the
clarify fallback and every ``requires_active_draft`` rule (all of ``revise``)
were invisible to it.

The semantic rung needs embeddings at request time; ``evaluation.harness.
cached_embeddings.CachedEmbeddingsClient`` supplies precomputed vectors
(``scripts/build_eval_embeddings.py``) so this still makes zero network calls.
Without a built cache the suite degrades to lexical-only, exactly as
production does without a live embeddings client -- see
``_build_matcher``.

``resolve_plan`` returning ``intent="clarify"`` is *not* an abstention the way
a bare ``None`` from the old deterministic-only call was: it is a committed
decision (ask the user) with its own ``source``. Recorded as such below, so
the report's ``source`` breakdown -- not the abstention rate -- is what shows
how often the ladder asks a clarifying question instead of deciding.
"""

import asyncio
from typing import Any, Optional

from app.ai.semantic.prototype_matcher import PrototypeMatcher
from app.ai.session.focus import DraftVersion, SessionFocus
from app.ai.workflows.planner import resolve_plan
from evaluation.harness.cached_embeddings import CachedEmbeddingsClient
from evaluation.harness.runner import EvalCase, EvalRun, load_cases, run_cases
from evaluation.metrics import Prediction

SUITE = "intents"
DATASET = "intents"

#: The gold set records whether a document is attached as a boolean; the planner
#: takes the document's storage path. Any non-empty path behaves identically for
#: every branch the planner has, so one placeholder stands in for all of them.
_DOCUMENT_PLACEHOLDER = "uploads/evrak_gold.pdf"

#: Stands in for a real `SessionFocus.active_draft` -- `resolve_plan` only
#: ever checks `is not None` on it (see `has_active_draft` in `planner.py`),
#: so the field values themselves are irrelevant placeholders.
_DUMMY_ACTIVE_DRAFT = DraftVersion(
    version=1,
    text="",
    correspondence_type="other_official",
    confidence_score=0.0,
    created_from="draft",
)


def _build_matcher() -> Optional[PrototypeMatcher]:
    """Build the semantic rung from the cached eval embeddings, if available.

    Returns:
        A matcher, or None when the cache hasn't been built yet -- the suite
        then measures the lexical layer alone, the same degradation
        production exhibits without a live embeddings client.
    """
    try:
        client = CachedEmbeddingsClient()
    except FileNotFoundError as exc:
        print(f"[intents] {exc}")
        return None

    cases = load_cases(DATASET)
    messages = [case.payload.get("message", "") for case in cases if case.payload.get("message")]
    missing = client.missing(messages)
    if missing:
        raise RuntimeError(
            f"{len(missing)} gold-set message(s) have no cached embedding "
            "(the gold set changed since the cache was built). Rerun: "
            "docker compose run --rm --no-deps backend python "
            "scripts/build_eval_embeddings.py"
        )

    matcher = PrototypeMatcher(client, model_name=client.model)
    return matcher if matcher.available else None


_MATCHER = _build_matcher()

#: Sources that mean "fusion did not commit on its own" -- with
#: ``llm_client=None`` here, ``resolve_plan`` always lands on ``clarify`` for
#: these cases, but the set also names the sources a *model*-backed call would
#: produce instead (``model``/``model_failed``, once Faz 4 wires those in) and
#: the retired ``context_default`` label from before fusion existed, so this
#: check keeps working unchanged as that lands. All are "escalated beyond
#: what this suite measures" for the ``expected_abstain`` gold cases.
_ESCALATION_SOURCES = frozenset({"clarify", "context_default", "model", "model_failed"})


def _escalated(observed: dict[str, Any]) -> bool:
    """Whether a decision came from beyond the lexical/semantic rungs."""
    return observed.get("source") in _ESCALATION_SOURCES


def _focus_from_payload(payload: dict[str, Any]) -> SessionFocus:
    """Build the `SessionFocus` a gold-set row implies."""
    active_draft = _DUMMY_ACTIVE_DRAFT if payload.get("active_draft") else None
    return SessionFocus(
        active_draft=active_draft,
        pending_clarification=payload.get("pending_clarification"),
    )


def decide(case: EvalCase) -> dict[str, Any]:
    """Run one gold-set case through the full (non-model) intent ladder.

    Args:
        case: The gold-set case.

    Returns:
        The observation dict: resolved intent, plan steps, the ladder's own
        ``source`` label, and whether it abstained. ``resolve_plan`` never
        actually abstains (it always returns a decision, ``clarify`` included)
        -- ``abstained`` is kept in the observation shape for
        ``to_predictions``/``failures`` below, always False.
    """
    document_id = _DOCUMENT_PLACEHOLDER if case.payload.get("document_attached") else None
    focus = _focus_from_payload(case.payload)

    decision = asyncio.run(
        resolve_plan(
            case.payload.get("message", ""),
            document_id,
            llm_client=None,
            previous_intent=case.payload.get("previous_intent"),
            matcher=_MATCHER,
            focus=focus,
        )
    )

    return {
        "intent": decision.intent,
        "steps": list(decision.steps),
        "source": decision.source,
        "confidence": decision.confidence,
        "abstained": False,
    }


def run() -> EvalRun:
    """Run the whole intent gold set.

    Returns:
        The completed run.
    """
    return run_cases(SUITE, DATASET, load_cases(DATASET), decide)


def to_predictions(run_result: EvalRun) -> list[Prediction]:
    """Convert a run into the shape the classification metrics consume.

    A case whose gold answer is ``expected_abstain: true`` is genuinely
    ambiguous -- the right behaviour is to escalate beyond the free layers, so
    landing on any of ``_ESCALATION_SOURCES`` counts as a *success*. Encoding
    that as expected/predicted ``"<abstain>"`` lets the same macro-F1 reward
    correct escalation instead of penalising it.

    Args:
        run_result: A completed intent run.

    Returns:
        One prediction per case.
    """
    predictions: list[Prediction] = []

    for result in run_result.results:
        wants_abstain = bool(result.case.expected.get("expected_abstain"))
        observed_intent = result.observed.get("intent")
        escalated = _escalated(result.observed)

        if wants_abstain:
            predictions.append(
                Prediction(
                    expected="<abstain>",
                    predicted="<abstain>" if escalated else observed_intent,
                    confidence=0.0 if escalated else float(result.observed.get("confidence", 1.0)),
                    abstained=False,
                )
            )
            continue

        predictions.append(
            Prediction(
                expected=str(result.case.expected.get("intent")),
                predicted=None if escalated else observed_intent,
                confidence=0.0 if escalated else float(result.observed.get("confidence", 1.0)),
                abstained=escalated,
            )
        )

    return predictions


def source_distribution(run_result: EvalRun) -> dict[str, int]:
    """Count how many decisions each mechanism produced.

    The number the deterministic-only harness could never show: how often
    the ladder actually reaches the clarify fallback, broken down by the
    exact mechanism (``fused``/``fused_semantic``/``compound``/
    ``clarification_resolved``/``clarify`` -- ``model``/``model_failed``
    never appear here since ``llm_client=None``).

    Args:
        run_result: A completed intent run.

    Returns:
        Source label -> case count, most common first.
    """
    counts: dict[str, int] = {}
    for result in run_result.results:
        source = str(result.observed.get("source"))
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def clarify_rate(run_result: EvalRun) -> float:
    """Share of cases the ladder answered with a clarifying question.

    This is the number K2 (short, unambiguous imperatives resolving to
    ``clarify`` instead of ``draft``) shows up in directly -- a regression
    here means the ladder is asking more questions it shouldn't need to.

    Args:
        run_result: A completed intent run.

    Returns:
        The clarify rate in [0, 1], or 0.0 for an empty run.
    """
    if not run_result.results:
        return 0.0
    clarified = sum(
        1 for result in run_result.results if result.observed.get("intent") == "clarify"
    )
    return clarified / len(run_result.results)


def failures(run_result: EvalRun) -> list[dict[str, Any]]:
    """List the cases the gate got wrong, for the report's detail section.

    Args:
        run_result: A completed intent run.

    Returns:
        One row per failing case, with enough context to act on it.
    """
    rows: list[dict[str, Any]] = []

    for result in run_result.results:
        expected_intent = result.case.expected.get("intent")
        wants_abstain = bool(result.case.expected.get("expected_abstain"))
        observed_intent = result.observed.get("intent")
        escalated = _escalated(result.observed)

        if wants_abstain:
            failed = not escalated
        else:
            failed = escalated or observed_intent != expected_intent

        if not failed:
            continue

        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "message": result.case.payload.get("message", ""),
                "document_attached": bool(result.case.payload.get("document_attached")),
                "previous_intent": result.case.payload.get("previous_intent"),
                "expected": "<abstain>" if wants_abstain else expected_intent,
                "observed": "<abstain>" if escalated else observed_intent,
                "source": result.observed.get("source"),
            }
        )

    return rows
