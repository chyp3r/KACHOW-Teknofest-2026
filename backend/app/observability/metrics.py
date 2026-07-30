from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

def init_metrics(app: FastAPI) -> None:
    """Initialize Prometheus FastAPI Instrumentator.
    
    This will hook into request/response flows and expose the /metrics endpoint.
    """
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
