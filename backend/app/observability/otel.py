import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


def init_tracing(app: FastAPI) -> None:
    """Wire OpenTelemetry distributed tracing for HTTP/DB/Redis/outbound-httpx
    spans.

    Complements Langfuse (`app.observability.tracer`), which only ever sees
    LLM calls routed through a LangChain callback -- Postgres queries,
    outbound `httpx` calls (Qdrant, Ollama) and the FastAPI request/response
    cycle itself have no Langfuse span today, so a slow chat turn cannot be
    attributed to model vs. database vs. vector store. OTel fills exactly
    that gap; the two are not redundant, see docs/deployment/observability.md
    for which question each one answers.

    No-ops -- does not even import the SDK/instrumentation modules, which
    would be pointless work with nowhere to send spans -- when
    `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, mirroring the Langfuse
    absent-key degrade in `app.observability.tracer`: a missing collector
    must never be the reason the API fails to boot.
    """
    if not settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        logger.info(
            "OTEL_EXPORTER_OTLP_ENDPOINT not set; OpenTelemetry tracing disabled."
        )
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: settings.PROJECT_NAME})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    RedisInstrumentor().instrument(tracer_provider=provider)

    # SQLAlchemyInstrumentor().instrument() with no `engine=`/`engines=` only
    # patches *future* create_engine/create_async_engine calls -- both of
    # this app's engines (`app.infrastructure.database.session.engine`/
    # `owner_engine`) are created at import time, before this function ever
    # runs, so they must be instrumented explicitly. AsyncEngine wraps a
    # sync Engine that actually emits the SQLAlchemy core events the
    # instrumentor hooks into, hence `.sync_engine` rather than the
    # AsyncEngine objects themselves. Both must go through a single
    # `instrument()` call via `engines=[...]` -- BaseInstrumentor guards
    # against being called twice on the same (singleton) instrumentor
    # instance, so a second `instrument(engine=...)` call for the second
    # engine would silently no-op (verified live: it logs "Attempting to
    # instrument while already instrumented" and only the first engine ends
    # up traced).
    from app.infrastructure.database.session import engine, owner_engine

    SQLAlchemyInstrumentor().instrument(
        engines=[engine.sync_engine, owner_engine.sync_engine],
        tracer_provider=provider,
    )

    logger.info(
        "OpenTelemetry tracing enabled, exporting to %s",
        settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
