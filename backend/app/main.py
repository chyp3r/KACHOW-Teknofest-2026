from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException

from app.api.exceptions import (
    BaseAppException,
    app_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.api.middleware import (
    ResponseTimeMiddleware,
    StructuredLoggingMiddleware,
)
from app.api.router import api_router
from app.core.config import settings
from app.observability.metrics import init_metrics
from app.observability.logger import setup_logging

# Initialize system logging formatters
setup_logging(settings.ENVIRONMENT)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# CORS Middleware (Allow all origins for local/development dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Register Middlewares (Calculates response time first, then logs)
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(ResponseTimeMiddleware)

# 2. Register Metrics (Prometheus /metrics endpoint)
init_metrics(app)

# 3. Register Global Exception Handlers
app.add_exception_handler(BaseAppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# 3. Include Routers
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
    }

