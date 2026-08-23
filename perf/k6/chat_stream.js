// Load test for POST /api/v1/chat/stream against a real, running stack
// (real Ollama, real Postgres/Redis/Qdrant) -- this is the one thing the
// e2e suite (backend/tests/e2e/test_chat_stream_sse_e2e.py) cannot cover,
// since it fakes the LLM client entirely to stay deterministic and fast.
//
// k6 has no first-class SSE client (see this script's own README note
// below). It sends a plain POST and lets k6 buffer the whole
// `text/event-stream` body like any other response -- `res.timings.waiting`
// is time-to-first-byte (roughly: time to the `session` event), `res.
// timings.duration` is the total time to the closing `data: [DONE]\n\n`
// line. What this transport genuinely cannot exercise: a client aborting
// mid-stream (see chat/router.py::_sse_response's is_disconnected() check)
// -- that needs a raw socket abort, which is exactly the gap backend/tests/
// e2e/conftest.py's own module docstring already calls out for
// ASGITransport. Neither harness covers it today.
//
// Run:
//   docker run --rm -i --network host \
//     -v "$(pwd)/perf/k6:/scripts" grafana/k6 run /scripts/chat_stream.js
// Needs a REQUIRE_AUTH-reachable backend with the default seeded accounts
// (see backend/app/core/config.py's SEED_* settings) -- override with
// K6_USERNAME/K6_PASSWORD for a non-default environment.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { commonThresholds, llmEndpointThreshold, budgets } from './lib/thresholds.js';

const BASE_URL = __ENV.K6_BASE_URL || 'http://localhost:8000';
const USERNAME = __ENV.K6_USERNAME || 'employee';
const PASSWORD = __ENV.K6_PASSWORD || 'Employee123!';

// See document_upload.js's identical constant for why this is needed at
// all: k6's own default per-request timeout (60s) is under a real drafting
// turn's cost, discovered empirically running that script first.
const REQUEST_TIMEOUT = `${budgets.workflow_ceiling_seconds}s`;

export const options = {
  vus: 2,
  duration: '1m',
  thresholds: { ...commonThresholds, ...llmEndpointThreshold('chat_stream') },
};

export function setup() {
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ username: USERNAME, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' }, tags: { endpoint: 'login' } }
  );
  if (res.status !== 200) {
    throw new Error(`setup login failed: ${res.status} ${res.body}`);
  }
  return { token: res.json('data.access_token') };
}

export default function (data) {
  const res = http.post(
    `${BASE_URL}/api/v1/chat/stream`,
    JSON.stringify({ message: 'Merhaba, izin talebi hakkında kısa bilgi verir misin?' }),
    {
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${data.token}`,
      },
      tags: { endpoint: 'chat_stream' },
      timeout: REQUEST_TIMEOUT,
    }
  );

  check(res, {
    'chat stream responded 200': (r) => r.status === 200,
    'chat stream is SSE': (r) =>
      (r.headers['Content-Type'] || '').indexOf('text/event-stream') === 0,
    'chat stream reached [DONE]': (r) => r.body.indexOf('data: [DONE]') !== -1,
  });

  sleep(1);
}
