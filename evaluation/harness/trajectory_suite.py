"""Measures the compiled planning graph's *trajectory*, not just its final
answer.

Nothing in this repo answered "did the planning graph run the node sequence
it was supposed to?" before this -- the 13 pre-existing "end-to-end" graph
tests (`backend/tests/integration/test_*.py`) each assert on one turn's final
`final_output`/interrupt payload, never on the path taken to get there. In a
multi-step orchestrator this is exactly the class of regression that slips
through: a node silently starts (or stops) firing while every downstream
value still happens to look right for the fixed gold input.

Cheap because `app.observability.run_recorder`'s `RunStepModel` already
records this shape in production (`step`, `status`, `duration_ms`) -- this
suite does not invent a new way to observe a run, it just reads the same
signal LangGraph itself already emits via `astream(..., stream_mode=
"updates")`: one event per top-level graph node super-step, in the order
they actually ran.

Deliberately measures *graph-node* trajectories (`planning`, `executor`,
`human_gate`, `focus`, `consolidate_memory`, ...), not the finer-grained
*plan-step* trajectory (`classification`, `brief`, `draft`, `routing`, ...)
`planner.PLAN_BY_INTENT` produces -- a multi-step plan's `executor` node
runs once per ready step (see `execute_step_node`'s own docstring on why:
no `StepSpec` is `parallel_safe` today), so a 4-step "draft" plan's
node-level trajectory is `[planning, executor, executor, executor, executor,
focus, consolidate_memory]`, and it is this repetition of `executor` --
correct at the graph level -- that a node-name check must expect. Measuring
plan-step identity too would require instrumenting `execute_step_node`
itself; the graph-node signal already catches the failure class this suite
exists for (a gate silently skipped, a loop that never terminates, a node
dropped from the graph) without touching production code at all.

Every sub-graph (`document_analysis_graph`, `rag_graph`, `draft_graph`,
`routing_graph`) is replaced with an `AsyncMock` returning a case-supplied,
plain-JSON result -- same reasoning as `evaluation.harness.intent_suite`'s
`llm_client=None`: this suite measures the *orchestrator's* routing logic,
not the sub-graphs' own generation quality (each of those either has no
eval suite of its own yet, or is covered indirectly by `draft_suite`).
`app.observability.run_recorder`'s three entry points are patched to
no-ops for the same reason `tests/integration/test_run_recording.py`
patches them for its *other* two tests: this suite must stay fully
offline, and unlike that file's own first test, this one has no interest
in asserting on the recorder call itself.
"""

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import MemorySaver

from app.ai.llms.base import BaseLLMClient, ToolCallResponse
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings
from evaluation.harness.runner import EvalCase, EvalRun, load_cases, run_cases

SUITE = "trajectories"
DATASET = "trajectories"

#: LangGraph's own marker for "a node called interrupt() and the run
#: paused" in `stream_mode="updates"` -- not a real node name, but the only
#: honest way to represent "reached human_gate but human_gate itself never
#: returned an update" in the node sequence (verified live: the preceding
#: `executor` events are real node updates, this one is not paired with a
#: `human_gate` update at all).
_INTERRUPT_MARKER = "__interrupt__"

_DEFAULT_DOCUMENT_ANALYSIS_RESULT: dict[str, Any] = {
    "document_type": "official_letter",
    "document_type_label": "Resmî Yazı",
    "summary": "",
    "fields": {},
    "missing_fields": [],
    "compliance_status": "compliant",
    "mevzuat_suggestions": [],
}


class _StubLLMClient(BaseLLMClient):
    """A trimmed, standalone copy of `backend/tests/conftest.py`'s
    `FakeLLMClient` -- duplicated rather than imported so this eval harness
    never depends on `backend/tests/`, which is free to reorganise or delete
    fixtures without touching `evaluation/`. Only the methods the assist
    step's streaming reply actually calls are implemented; every gold case
    here keeps `document_id` empty, so the drafting/classification/tool
    paths that would need `generate_structured`/`generate_with_tools` to
    return something meaningful never run against this client at all (they
    run against the mocked sub-graphs instead -- see this module's
    docstring).
    """

    def __init__(self, stream_chunks: Optional[list[str]] = None) -> None:
        self.stream_chunks = stream_chunks or ["Elbette, yardımcı olabilirim."]

    async def generate(self, messages, temperature=None, max_tokens=None, **kwargs) -> str:
        return ""

    async def generate_structured(self, messages, response_model, temperature=None, **kwargs) -> Any:
        return None

    def stream(self, messages, temperature=None, max_tokens=None, **kwargs):
        async def _gen():
            for chunk in self.stream_chunks:
                yield chunk

        return _gen()

    async def generate_with_tools(
        self, messages, tools, temperature=None, max_tokens=None, **kwargs
    ) -> ToolCallResponse:
        return ToolCallResponse()


async def _run_trajectory(case: EvalCase) -> dict[str, Any]:
    """Compile a fresh graph for this one case and stream it to completion
    (or to its first pause).

    A fresh graph/checkpointer per case, never reused across cases -- the
    `_last_ran_step` and per-thread checkpoint state `route_after_step`
    reads would otherwise leak between gold-set rows that happen to share
    a `thread_id`.
    """
    document_analysis_result = (
        case.payload.get("document_analysis_result") or _DEFAULT_DOCUMENT_ANALYSIS_RESULT
    )
    graph = create_planning_graph(
        llm_client=_StubLLMClient(),
        fast_llm_client=_StubLLMClient(),
        document_analysis_graph=AsyncMock(
            ainvoke=AsyncMock(return_value=document_analysis_result)
        ),
        rag_graph=AsyncMock(),
        draft_graph=AsyncMock(ainvoke=AsyncMock(return_value=case.payload.get("draft_result") or {})),
        routing_graph=AsyncMock(
            ainvoke=AsyncMock(return_value=case.payload.get("routing_result") or {})
        ),
        checkpointer=MemorySaver(),
    )
    config = {"configurable": {"thread_id": f"trajectory-{case.id}"}}

    node_sequence: list[str] = []
    with (
        patch("app.ai.workflows.planning_graph.start_run", new=AsyncMock()),
        patch("app.ai.workflows.planning_graph.record_step", new=AsyncMock()),
        patch("app.ai.workflows.planning_graph.end_run", new=AsyncMock()),
    ):
        async for event in graph.astream(
            {"input_text": case.payload["message"], "document_id": None},
            config=config,
            stream_mode="updates",
        ):
            node_sequence.extend(event.keys())

    paused_at: Optional[str] = None
    if node_sequence and node_sequence[-1] == _INTERRUPT_MARKER:
        snapshot = await graph.aget_state(config)
        if snapshot.next:
            paused_at = snapshot.next[0]

    return {"node_sequence": node_sequence, "paused_at": paused_at}


def decide(case: EvalCase) -> dict[str, Any]:
    return asyncio.run(_run_trajectory(case))


def run() -> EvalRun:
    """Run the whole trajectory gold set, fully offline.

    Every gold case here has empty `classification.fields`, which would
    otherwise always open the pre-draft `brief_gate` first (see
    `test_hitl_flow.py`'s own note on the same trade-off) -- disabled for
    the duration of this run so a case's `expected.node_sequence` only ever
    has to account for the one gate it's actually testing. Restored in
    `finally` since `settings` is a process-wide singleton other suites in
    the same `generate_report.py --suite all` run also read.
    """
    original = settings.HITL_BRIEF_GATE_ENABLED
    settings.HITL_BRIEF_GATE_ENABLED = False
    try:
        return run_cases(SUITE, DATASET, load_cases(DATASET), decide)
    finally:
        settings.HITL_BRIEF_GATE_ENABLED = original


def _levenshtein_over_tokens(observed: list[str], expected: list[str]) -> int:
    """Edit distance between two node-name sequences.

    `Levenshtein.distance` operates on strings (character sequences); a
    node name is a multi-character token, so each distinct token across
    both sequences is mapped to one private-use-area code point first --
    the standard trick for reusing a string edit-distance function on a
    sequence of arbitrary tokens without pulling in a second dependency
    for token-level edit distance.
    """
    import Levenshtein

    alphabet: dict[str, str] = {}

    def _encode(seq: list[str]) -> str:
        chars = []
        for token in seq:
            if token not in alphabet:
                alphabet[token] = chr(0xE000 + len(alphabet))
            chars.append(alphabet[token])
        return "".join(chars)

    return Levenshtein.distance(_encode(observed), _encode(expected))


def sequence_summary(run_result: EvalRun) -> dict[str, Any]:
    """Score a completed trajectory run.

    Returns:
        ``exact_match_rate``: share of cases whose observed node sequence is
            byte-identical to the gold sequence.
        ``mean_edit_distance``: mean Levenshtein distance (in node-visits)
            between observed and expected -- unlike exact match, this
            distinguishes "one extra loop of executor" from "the whole
            trajectory is unrecognisable".
        ``unexpected_node_rate``: of all node-visits observed across the
            whole run, the share that named a node absent from that case's
            *own* expected sequence entirely -- the number that answers "is
            the graph visiting somewhere it structurally should never have
            gone for this input", as opposed to just running a known node
            the wrong number of times.
        ``paused_at_mismatches``: cases where the gold set records an
            expected pause point (``expected.paused_at``) and the observed
            one differs -- exact-match already catches this via
            ``__interrupt__``, but this states *which node* the run
            actually paused at, for the failure detail table.
    """
    exact_matches = 0
    total_distance = 0
    unexpected_visits = 0
    total_visits = 0
    paused_at_mismatches: list[dict[str, Any]] = []

    for result in run_result.results:
        expected_seq = list(result.case.expected.get("node_sequence") or [])
        observed_seq = list(result.observed.get("node_sequence") or [])

        if observed_seq == expected_seq:
            exact_matches += 1
        total_distance += _levenshtein_over_tokens(observed_seq, expected_seq)

        expected_nodes = set(expected_seq)
        total_visits += len(observed_seq)
        unexpected_visits += sum(1 for node in observed_seq if node not in expected_nodes)

        expected_paused_at = result.case.expected.get("paused_at")
        if expected_paused_at is not None:
            observed_paused_at = result.observed.get("paused_at")
            if observed_paused_at != expected_paused_at:
                paused_at_mismatches.append(
                    {
                        "id": result.case.id,
                        "expected": expected_paused_at,
                        "observed": observed_paused_at,
                    }
                )

    cases = len(run_result.results)
    return {
        "cases": cases,
        "exact_match_rate": exact_matches / cases if cases else 0.0,
        "mean_edit_distance": total_distance / cases if cases else 0.0,
        "unexpected_node_rate": unexpected_visits / total_visits if total_visits else 0.0,
        "paused_at_mismatches": paused_at_mismatches,
    }


def failures(run_result: EvalRun) -> list[dict[str, Any]]:
    """List the cases whose observed trajectory did not exactly match gold."""
    rows: list[dict[str, Any]] = []
    for result in run_result.results:
        expected_seq = list(result.case.expected.get("node_sequence") or [])
        observed_seq = list(result.observed.get("node_sequence") or [])
        if observed_seq == expected_seq:
            continue
        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "message": result.case.payload.get("message", ""),
                "expected": expected_seq,
                "observed": observed_seq,
                "edit_distance": _levenshtein_over_tokens(observed_seq, expected_seq),
            }
        )
    return rows
