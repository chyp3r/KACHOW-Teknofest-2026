// Shared k6 thresholds, keyed off the exact same budget numbers the
// backend's own AI workflows enforce (perf/k6/lib/budgets.json, written by
// scripts/export_budgets.py from app.ai.policy.schema.BudgetPolicy).
//
// k6 never imports Python (see scripts/export_budgets.py's own module
// docstring for why) -- this file is the one place that reads the exported
// JSON, so every k6 script that cares about an LLM-endpoint budget imports
// its threshold from here instead of hardcoding a duplicate number that can
// silently drift from the policy.
//
// open() resolves relative to *this file*, and only accepts a literal
// (build-time) path -- a k6 requirement, not a stylistic choice.
const budgets = JSON.parse(open('./budgets.json'));

// General HTTP health: less than 1% of requests may fail, across every
// scenario in every script that imports this.
export const commonThresholds = {
  http_req_failed: ['rate<0.01'],
};

// A shallow, no-dependency-probing health check must answer fast -- this is
// the one absolute (not budget-derived) number in this file, matching what
// a load balancer / uptime probe would actually require.
export const healthThresholds = {
  'http_req_duration{endpoint:health}': ['p(95)<200'],
};

// Every LLM-backed endpoint is graded against the whole-workflow ceiling
// (BudgetPolicy.workflow_ceiling_seconds), not a tight number -- k6 cannot
// see which node a slow request spent its time in the way
// evaluation/latency/budget_report.py (Workstream E3) can from real
// per-node Prometheus histograms; k6's only job here is "did the whole
// request blow the outer budget", the coarse backstop those node-level
// numbers already imply.
export function llmEndpointThreshold(endpointTag) {
  const ceilingMs = budgets.workflow_ceiling_seconds * 1000;
  const key = `http_req_duration{endpoint:${endpointTag}}`;
  return { [key]: [`p(95)<${ceilingMs}`] };
}

export { budgets };
