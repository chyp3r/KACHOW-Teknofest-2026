from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

def init_metrics(app: FastAPI) -> None:
    """Prometheus FastAPI Instrumentator'ı başlatır.

    Bu, request/response akışlarına bağlanacak ve /metrics endpoint'ini açığa çıkaracaktır.
    """
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
