import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger(__name__)


def init_tracing(app: FastAPI) -> None:
    """HTTP/DB/Redis/giden-httpx span'leri için OpenTelemetry dağıtık
    tracing'i bağlar.

    Langfuse'u (`app.observability.tracer`) tamamlar; o sadece bir LangChain
    callback'i üzerinden yönlendirilen LLM çağrılarını görür -- Postgres
    sorguları, giden `httpx` çağrıları (Qdrant, Ollama) ve FastAPI
    request/response döngüsünün kendisi bugün hiçbir Langfuse span'ine
    sahip değildir, bu yüzden yavaş bir sohbet turu model mi, veritabanı mı
    yoksa vektör deposu mu diye atfedilemez. OTel tam olarak bu boşluğu
    doldurur; ikisi birbirinin yerini tutmaz, her birinin hangi soruyu
    yanıtladığı için docs/deployment/observability.md'ye bakın.

    `OTEL_EXPORTER_OTLP_ENDPOINT` ayarlanmadığında hiçbir şey yapmaz --
    span gönderilecek yer olmadığında anlamsız bir iş olacağından SDK/
    instrumentation modüllerini import bile etmez -- bu,
    `app.observability.tracer`'daki Langfuse anahtar-yok bozulma
    davranışını yansıtır: eksik bir collector, API'nin açılışının
    başarısız olmasının nedeni olmamalıdır.
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

    # `engine=`/`engines=` verilmeden SQLAlchemyInstrumentor().instrument()
    # sadece *gelecekteki* create_engine/create_async_engine çağrılarını
    # yamalar -- bu uygulamanın her iki engine'i de
    # (`app.infrastructure.database.session.engine`/`owner_engine`) bu
    # fonksiyon hiç çalışmadan önce, import zamanında oluşturulur, bu
    # yüzden açıkça instrument edilmeleri gerekir. AsyncEngine, instrumentor'ın
    # bağlandığı SQLAlchemy core event'lerini fiilen yayan bir sync Engine'i
    # sarmalar, bu yüzden AsyncEngine nesnelerinin kendisi yerine
    # `.sync_engine` kullanılır. Her ikisi de `engines=[...]` üzerinden tek
    # bir `instrument()` çağrısından geçmelidir -- BaseInstrumentor aynı
    # (singleton) instrumentor örneğinin iki kez çağrılmasına karşı korur,
    # bu yüzden ikinci engine için ikinci bir `instrument(engine=...)`
    # çağrısı sessizce hiçbir şey yapmaz (canlıda doğrulandı: "Attempting to
    # instrument while already instrumented" logunu basar ve sadece ilk
    # engine trace edilmiş olarak kalır).
    from app.infrastructure.database.session import engine, owner_engine

    SQLAlchemyInstrumentor().instrument(
        engines=[engine.sync_engine, owner_engine.sync_engine],
        tracer_provider=provider,
    )

    logger.info(
        "OpenTelemetry tracing enabled, exporting to %s",
        settings.OTEL_EXPORTER_OTLP_ENDPOINT,
    )
