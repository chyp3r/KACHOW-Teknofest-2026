import logging
from fastapi import Request
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse

from app.api.exceptions.base import BaseAppException
from app.api.responses.error import ErrorResponse

logger = logging.getLogger(__name__)


async def app_exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """Özel BaseAppException hiyerarşisi için genel işleyici."""
    logger.error(f"Application error [{exc.error_code}]: {exc.message}", exc_info=True)
    # Middleware tarafından hesaplanıp request state içinde saklanmışsa yanıt süresini al
    response_time = getattr(request.state, "response_time_ms", None)
    meta = {"response_time_ms": response_time} if response_time else None
    
    return ErrorResponse(
        code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
        details=exc.details,
        meta=meta,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic/FastAPI istek gövdesi doğrulama hataları için genel işleyici."""
    logger.warning(f"Validation error on path {request.url.path}: {exc.errors()}")

    # Pydantic hatalarını daha sade ve okunabilir bir yapıya dönüştür
    formatted_errors = []
    for err in exc.errors():
        formatted_errors.append({
            "field": ".".join(str(loc) for loc in err.get("loc", [])),
            "type": err.get("type"),
            "msg": err.get("msg"),
        })
        
    response_time = getattr(request.state, "response_time_ms", None)
    meta = {"response_time_ms": response_time} if response_time else None
    
    return ErrorResponse(
        code="VALIDATION_ERROR",
        message="Girdi doğrulaması başarısız oldu.",
        status_code=422,
        details={"validation_errors": formatted_errors},
        meta=meta,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Standart FastAPI/Starlette HTTPException için genel işleyici."""
    logger.warning(f"HTTPException [{exc.status_code}]: {exc.detail}")
    response_time = getattr(request.state, "response_time_ms", None)
    meta = {"response_time_ms": response_time} if response_time else None
    
    return ErrorResponse(
        code="HTTP_ERROR",
        message=str(exc.detail),
        status_code=exc.status_code,
        meta=meta,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Ele alınmamış genel sistem istisnaları için yedek genel işleyici."""
    logger.critical(f"Unhandled system error: {exc}", exc_info=True)
    response_time = getattr(request.state, "response_time_ms", None)
    meta = {"response_time_ms": response_time} if response_time else None

    # Üretim ortamında ayrıntıları gizle ama hata ayıklama için açıklayıcı bilgiyi koru
    details = {"error_type": exc.__class__.__name__, "message": str(exc)}

    return ErrorResponse(
        code="INTERNAL_SERVER_ERROR",
        message="Beklenmeyen bir dahili sunucu hatası oluştu.",
        status_code=500,
        details=details,
        meta=meta,
    )
