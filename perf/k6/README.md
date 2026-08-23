# k6 load tests (Workstream E2)

Real HTTP load against a real running stack (real Ollama, real Postgres,
real Redis, real Qdrant) -- the wall-clock counterpart to the fast,
deterministic e2e suite (`backend/tests/e2e/`), which fakes the LLM/
embeddings clients on purpose to stay fast and reproducible. Neither
replaces the other: e2e proves correctness under real RLS/auth/lifespan;
these scripts measure how the same endpoints behave under real model
latency and concurrent load.

## Why k6, not locust

One load-testing tool, not two. k6 already gives everything this project
needs: threshold-as-gate (`options.thresholds`, checked in CI-friendly pass/
fail terms), scenario executors (`ramping-arrival-rate` etc., not used yet
but available without adding a dependency), and a single static Go binary
with no Python runtime or virtualenv needed in CI. locust's actual
differentiator -- writing load scenarios in Python to reuse application
code -- doesn't apply here: what these scripts drive is bearer-token HTTP
and an SSE-shaped response body, neither of which needs an `app.*` import.
Running both would mean two threshold definitions that can silently drift
apart, and drift is never caught in the tool nobody's actively watching.
Decided once, not revisited per script.

## Why k6 can't fully exercise `/chat/stream`

k6 has no first-class SSE client. `chat_stream.js` sends a plain
`http.post()` and lets k6 buffer the whole `text/event-stream` body like any
other response: `res.timings.waiting` is time-to-first-byte (roughly, time
to the `session` event), `res.timings.duration` is total time to the
closing `data: [DONE]\n\n` line. That is enough to catch a real regression
in either number.

What it genuinely cannot exercise: a client aborting mid-stream (see
`backend/app/domains/chat/router.py::_sse_response`'s
`request.is_disconnected()` check). That needs a raw socket abort a
buffering HTTP client never performs -- the exact same gap
`backend/tests/e2e/conftest.py`'s own module docstring already documents for
`ASGITransport`. Today, nothing in this repo exercises that path directly;
it would need a raw-socket test client (or a k6 scenario that opens a
connection and kills it), which is out of scope for this workstream.

## `budgets.json` is generated, not hand-written

`lib/budgets.json` is written by `scripts/export_budgets.py` from the live
`app.ai.policy.schema.BudgetPolicy` -- never edited by hand. Regenerate it
after any policy change:

```bash
docker compose run --rm --no-deps backend python scripts/export_budgets.py
```

`backend/tests/unit/ai/test_budget_export_freshness.py` fails the moment the
committed file and the running policy drift apart. `lib/thresholds.js`
reads the LLM-endpoint threshold from this file (`workflow_ceiling_seconds`)
rather than hardcoding a number that could silently diverge from it.

## Running

Needs a real running stack (`make bootstrap` or `make up`) with the default
seeded accounts (`backend/app/core/config.py`'s `SEED_*` settings) --
override `K6_USERNAME`/`K6_PASSWORD` for a non-default environment, and
`K6_BASE_URL` if the backend isn't at the default `http://localhost:8000`.

```bash
# Health, low load, ~30s.
docker run --rm -i -v "$(pwd)/perf/k6:/scripts" \
  -e K6_BASE_URL=http://host.docker.internal:8000 \
  grafana/k6 run /scripts/smoke.js

# Chat streaming, real Ollama.
docker run --rm -i -v "$(pwd)/perf/k6:/scripts" \
  -e K6_BASE_URL=http://host.docker.internal:8000 \
  grafana/k6 run /scripts/chat_stream.js

# Document upload + analysis, real Ollama + Qdrant. Rate-limited at
# 10 req/60s per IP (documents:analyze) -- document_upload.js already
# paces itself under that.
docker run --rm -i -v "$(pwd)/perf/k6:/scripts" \
  -e K6_BASE_URL=http://host.docker.internal:8000 \
  grafana/k6 run /scripts/document_upload.js
```

`--network host` was tried first and rejected: Docker Desktop (macOS/
Windows) doesn't support it the way Linux does, so `host.docker.internal`
plus an explicit `K6_BASE_URL` is the one invocation that works
identically everywhere, including whatever CI runner Workstream I
eventually adds.

## What's here

- `smoke.js` -- shallow + deep health checks, low steady load.
- `chat_stream.js` -- authenticated `POST /chat/stream`, real Ollama.
- `document_upload.js` -- authenticated multipart upload to
  `POST /documents/analyze`, real Ollama + Qdrant. `fixtures/sample.pdf` is
  a small real PDF (reportlab-written, not a hand-rolled byte string --
  `DocumentService._validate_upload`'s magic-byte check needs a real one).
- `lib/thresholds.js` -- shared thresholds; the one place that reads
  `lib/budgets.json`.
- `lib/budgets.json` -- generated, see above.
