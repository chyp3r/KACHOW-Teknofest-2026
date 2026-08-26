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
from app.observability.otel import init_tracing
from app.observability.transfer_metrics import init_transfer_metrics
from app.observability.logger import setup_logging

# Sistem loglama formatlayıcılarını başlat
setup_logging(settings.ENVIRONMENT)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# CORS: "*" değil, açık bir origin izin listesi. Tarayıcılar allow_credentials=True
# ile birlikte "*" kullanımını doğrudan reddeder; bu yüzden önceki yapılandırma
# sadece fazla izin vermekle kalmıyor -- kimlik bilgisi taşıyan her istekte
# sessizce başarısız oluyordu.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Son eklenen = en dışta çalışır (Starlette middleware'leri kayıt sırasının
# tersinde uygular), böylece request_id, diğer tüm middleware'ler ve her route
# handler çalışmadan önce zaten ayarlanmış olur.
app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(ResponseTimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)
# app.infrastructure.database.session.get_db fonksiyonunun Postgres RLS
# GUC'lerini uygulamak için okuduğu tenant ContextVar'ını ayarlar -- yukarıdaki
# CorrelationIdMiddleware ile aynı sebeple, herhangi bir route dependency'si
# (get_db dahil) çalışmadan önce çalışmalıdır.
app.add_middleware(TenantContextMiddleware)

# Prometheus /metrics: varsayılan HTTP enstrümantasyonu artı AI'a özgü
# toplayıcılar (node/LLM gecikmesi, taslak skorları, HITL sayaçları, ...).
init_metrics(app)
init_ai_metrics()
init_company_metrics()
init_transfer_metrics()

# Altyapı seviyesinde izleme (HTTP/DB/Redis/giden-httpx span'leri) --
# OTEL_EXPORTER_OTLP_ENDPOINT ayarlanmamışsa hiçbir şey yapmaz. Bkz.
# app/observability/otel.py.
init_tracing(app)

app.add_exception_handler(BaseAppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# /health, /api/v1/health altında yaşar (app.domains.system) -- burada ayrı bir
# bare /health yoktur; eskiden bu, aynı bilgi için farklı şekilli bir yanıt
# döndürürdü.
app.include_router(api_router, prefix=settings.API_V1_STR)

