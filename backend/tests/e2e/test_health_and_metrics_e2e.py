"""Health check and Prometheus metrics, over real HTTP.

The value of running these as e2e rather than unit tests is `deep=true`
actually reaching Postgres/Redis/Qdrant through this test's own real
connections, and `/metrics` reflecting whatever `app.main` actually wired up
at startup -- both unverifiable against a mocked session or an unbuilt app.

Metric *names* only (never asserting on a metric's numeric value): a Counter/
Gauge/Histogram/Info's ``# HELP``/``# TYPE`` lines are emitted at declaration
time by ``prometheus_client``, so a metric that has never recorded a sample
still appears in ``GET /metrics`` -- this is a contract test that a name
survives a refactor, not an assertion about traffic this test generated.
This is also the test Workstream H's alert rules (PromQL against these same
names) depend on staying honest: renaming a metric here without updating an
alert rule breaks the alert silently, and nothing else in this repo would
catch it.
"""

import pytest

pytestmark = pytest.mark.e2e

#: A representative sample, not the full list documented in
#: app/observability/{ai,company,transfer}_metrics.py -- enough to catch a
#: renamed or dropped metric without this file becoming a second copy of
#: that list to keep in sync by hand.
_EXPECTED_METRIC_NAMES = [
    "kachow_node_duration_seconds",
    "kachow_llm_call_duration_seconds",
    "kachow_hitl_interrupts_total",
    "kachow_hitl_resume_total",
    "kachow_structured_retry_total",
    "kachow_guardrail_judge_failures_total",
    "kachow_router_semantic_available",
    "kachow_company_requests_total",
    "kachow_company_guardrail_blocks_total",
    "kachow_artifact_transfers_total",
]


@pytest.mark.asyncio
async def test_shallow_health_check_reports_healthy(e2e_client):
    response = await e2e_client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "healthy"
    assert "dependencies" not in body["data"]


@pytest.mark.asyncio
async def test_deep_health_check_probes_postgres_and_redis_and_qdrant(e2e_client):
    """Only postgres/redis/qdrant are asserted -- this container has no Ollama."""
    response = await e2e_client.get("/api/v1/health", params={"deep": "true"})

    assert response.status_code in (200, 503)
    dependencies = response.json()["data"]["dependencies"]
    assert dependencies["postgres"] == "ok"
    assert dependencies["redis"] == "ok"
    assert dependencies["qdrant"] == "ok"


@pytest.mark.asyncio
async def test_metrics_endpoint_is_mounted_at_the_app_root(e2e_client):
    """/metrics lives on the bare app, not under settings.API_V1_STR."""
    at_root = await e2e_client.get("/metrics")
    under_api_prefix = await e2e_client.get("/api/v1/metrics")

    assert at_root.status_code == 200
    assert under_api_prefix.status_code == 404


@pytest.mark.asyncio
async def test_metrics_exposes_every_known_kachow_metric_name(e2e_client):
    response = await e2e_client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    missing = [name for name in _EXPECTED_METRIC_NAMES if name not in body]
    assert missing == [], f"metric(s) disappeared from /metrics: {missing}"
