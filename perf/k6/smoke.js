// Smoke test: is the backend up and answering fast, at low, steady load.
//
// Run against a real running stack (the health check needs real
// Postgres/Redis/Qdrant behind it -- see backend/app/domains/system/
// router.py::build_health_payload):
//
//   docker run --rm -i --network host \
//     -v "$(pwd)/perf/k6:/scripts" grafana/k6 run /scripts/smoke.js
//
// (or `make perf-smoke`, which wires the network/volume the same way).
// BASE_URL defaults to the host-exposed dev backend port.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { commonThresholds, healthThresholds } from './lib/thresholds.js';

const BASE_URL = __ENV.K6_BASE_URL || 'http://localhost:8000';

export const options = {
  vus: 3,
  duration: '30s',
  thresholds: { ...commonThresholds, ...healthThresholds },
};

export default function () {
  const shallow = http.get(`${BASE_URL}/api/v1/health`, {
    tags: { endpoint: 'health' },
  });
  check(shallow, {
    'shallow health is 200': (res) => res.status === 200,
    'shallow health reports healthy': (res) => {
      const body = res.json();
      return body && body.data && body.data.status === 'healthy';
    },
  });

  // Deep health is deliberately excluded from the `health` tag/threshold
  // above: it fans out to Postgres/Redis/Qdrant/Ollama (see
  // build_health_payload's own `deep` branch) and is allowed to be slower --
  // it exists to report *which* dependency is unhealthy, not to be fast.
  const deep = http.get(`${BASE_URL}/api/v1/health?deep=true`, {
    tags: { endpoint: 'health_deep' },
  });
  check(deep, {
    'deep health responds': (res) => res.status === 200 || res.status === 503,
  });

  sleep(1);
}
