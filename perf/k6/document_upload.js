// Load test for POST /api/v1/documents/analyze against a real, running
// stack (real extraction pipeline, real Ollama classification, real Qdrant
// indexing) -- the wall-clock counterpart to backend/tests/e2e/
// test_document_upload_analysis_e2e.py, which fakes the LLM/embeddings
// clients to stay deterministic and fast.
//
// fixtures/sample.pdf is a small, real reportlab-written PDF (not a
// hand-rolled byte string) -- DocumentService._validate_upload runs a
// magic-byte/real-parse integrity check a fake byte string is not
// guaranteed to survive (same reasoning as backend/tests/e2e/conftest.py's
// own make_pdf_bytes fixture).
//
// Run:
//   docker run --rm -i --network host \
//     -v "$(pwd)/perf/k6:/scripts" grafana/k6 run /scripts/document_upload.js
// Needs a REQUIRE_AUTH-reachable backend with the default seeded accounts
// (see backend/app/core/config.py's SEED_* settings) -- override with
// K6_USERNAME/K6_PASSWORD for a non-default environment. Rate-limited at
// 10 requests/60s per IP (documents:analyze, see backend/app/domains/
// documents/router.py) -- vus/duration below stay comfortably under that.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { commonThresholds, llmEndpointThreshold, budgets } from './lib/thresholds.js';

const BASE_URL = __ENV.K6_BASE_URL || 'http://localhost:8000';
const USERNAME = __ENV.K6_USERNAME || 'employee';
const PASSWORD = __ENV.K6_PASSWORD || 'Employee123!';

// k6's own default per-request timeout (60s) is well under this endpoint's
// real cost -- document analysis alone runs several structured LLM calls in
// sequence (classification, compliance, guardrail, mevzuat suggestion; see
// app/ai/workflows/document_analysis_graph.py), discovered empirically the
// first time this script hit k6's default and errored with "request
// timeout" partway through a real run. Matches the same ceiling the
// backend itself enforces (BudgetPolicy.workflow_ceiling_seconds).
const REQUEST_TIMEOUT = `${budgets.workflow_ceiling_seconds}s`;

const samplePdf = open('./fixtures/sample.pdf', 'b');

export const options = {
  vus: 1,
  duration: '1m',
  thresholds: { ...commonThresholds, ...llmEndpointThreshold('document_upload') },
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
    `${BASE_URL}/api/v1/documents/analyze`,
    { file: http.file(samplePdf, 'sample.pdf', 'application/pdf') },
    {
      headers: { Authorization: `Bearer ${data.token}` },
      tags: { endpoint: 'document_upload' },
      timeout: REQUEST_TIMEOUT,
    }
  );

  check(res, {
    'upload+analysis responded 200': (r) => r.status === 200,
    'response has a storage_path': (r) => {
      const body = r.json();
      return body && body.data && !!body.data.storage_path;
    },
  });

  // documents:analyze is rate-limited at 10/60s per IP -- this pacing keeps
  // a single VU well under that regardless of how fast analysis itself
  // returns.
  sleep(8);
}
