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
    CorrelationIdMiddleware,
    ResponseTimeMiddleware,
    StructuredLoggingMiddleware,
    TenantContextMiddleware,
)
from app.api.router import api_router
from app.core.config import settings
from app.core.constants.system import CORS_ORIGINS
from app.lifespan import lifespan
from app.observability.ai_metrics import init_ai_metrics
from app.observability.company_metrics import init_company_metrics
from app.observability.metrics import init_metrics
from app.observability.logger import setup_logging

# Initialize system logging formatters
setup_logging(settings.ENVIRONMENT)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS: an explicit origin allowlist, not "*". Browsers reject "*" combined
# with allow_credentials=True outright, so the previous configuration was not
# just permissive -- it silently failed for every credentialed request.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registered last = runs outermost (Starlette applies middleware in reverse
# registration order), so request_id is already set before every other
# middleware and every route handler runs.
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(ResponseTimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
# Sets the tenant ContextVar app.infrastructure.database.session.get_db reads
# to apply Postgres RLS's GUCs -- must run before any route dependency (incl.
# get_db itself) executes, same as CorrelationIdMiddleware above.
app.add_middleware(TenantContextMiddleware)

# Prometheus /metrics: default HTTP instrumentation plus the AI-specific
# collectors (node/LLM latency, draft scores, HITL counters, ...).
init_metrics(app)
init_ai_metrics()
init_company_metrics()

# Register Global Exception Handlers
app.add_exception_handler(BaseAppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# Include Routers. /health lives under /api/v1/health (app.domains.system) --
# no separate bare /health here, which used to return a differently-shaped
# response from the same information.
app.include_router(api_router, prefix=settings.API_V1_STR)

