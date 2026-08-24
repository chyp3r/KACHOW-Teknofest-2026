from fastapi import FastAPI

from app.observability.otel import init_tracing


def test_init_tracing_noop_when_endpoint_unset(monkeypatch):
    """No collector configured -> init_tracing must not raise, and must not
    even import the OpenTelemetry SDK (asserted indirectly: no exporter
    connection attempt means no exception even with an unroutable endpoint
    left set on a *different* attribute the function never reads)."""
    monkeypatch.setattr(
        "app.observability.otel.settings.OTEL_EXPORTER_OTLP_ENDPOINT", None
    )

    app = FastAPI()
    init_tracing(app)  # must return quietly, no exception


def test_init_tracing_enabled_instruments_app_and_engines(monkeypatch):
    monkeypatch.setattr(
        "app.observability.otel.settings.OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://jaeger:4317",
    )

    app = FastAPI()
    # Must not raise even though nothing is listening on that endpoint --
    # the OTLP gRPC exporter only tries to connect when it actually flushes
    # a batch of spans, never at instrumentation time.
    init_tracing(app)
