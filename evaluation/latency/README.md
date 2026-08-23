# Latency budget report (Workstream E3)

`budget_report.py` reports observed per-node latency against
`app.ai.policy.schema.BudgetPolicy.node_seconds` -- the answer to "is any
node's real-world p95 creeping up on the timeout that would degrade or fail
it".

## Why observed, not synthetic

This script never re-times a node itself. It reads the real
`kachow_node_duration_seconds` Prometheus histogram off the running
backend's own `/metrics`, populated by real production traffic (or a k6 run,
Workstream E2). Synthetically re-timing a node on a dev laptop would measure
the laptop, not the system -- the same reasoning `evaluation/README.md`
gives for why this repo's evaluation suites are deterministic and LLM-free
rather than re-running a model to "check" it.

## Running

Needs the `backend` service actually running (traffic has to have hit it
first for there to be anything to report):

```bash
docker compose run --rm backend python -m evaluation.latency.budget_report
```

`--base-url` overrides the target if not running against the compose
service's own DNS name (`http://backend:8000` by default) -- e.g. from a
host-side script: `--base-url http://localhost:8000`.

Exit code is 1 if any node's p95 exceeds 0.8x its budget ("nearly
exhausted"), 0 otherwise -- safe to wire into a CI job once Workstream I's
CI exists, without further changes.

## A real gap this script's own first run found

`NODE_DURATION`'s Prometheus histogram (`app/observability/ai_metrics.py`)
used `prometheus_client`'s default bucket boundaries, which top out at
10.0s. Every real node observation (this document type's nodes routinely
run 10-180s) was silently collapsing into the `+Inf` bucket, so every
p50/p95/p99 estimate read back as the same floor value regardless of the
true duration -- discovered running this script against a live `analyze`
call. Fixed by giving `NODE_DURATION` explicit buckets spanning
sub-second to past `workflow_ceiling_seconds` (480s), with resolution
concentrated in the 25-180s band the actual budgets live in.

## A disclosed, still-open gap

Only 7 of `BudgetPolicy.node_seconds`'s 9 keys are actually instrumented
today: `analyze`, `scan_sensitivity`, `retrieve_mevzuat`, `suggest_mevzuat`,
`route` (via the shared `@node_timeout` decorator, `app/ai/workflows/
resilience.py`) and `retrieve_examples`, `retrieve_source_chunks` (inline,
`app/ai/workflows/draft_graph.py`). `writer` and `assist` are not -- both
have multi-path exception handling (streamed generation with a partial-
preview side channel for `writer`; a fallback-tier retry for `assist`) that
this workstream judged too risky to instrument correctly without its own
focused review, rather than bolt on blindly as a side effect of a
reporting script. `budget_report.py` reports "no observations yet" for
these two honestly rather than pretending they're covered --
`backend/tests/performance/test_node_budget_coverage.py` documents the
same gap as a known exception, not a silent one.
