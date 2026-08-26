import json
import logging
import sys
from datetime import datetime, timezone

#: Standart bir LogRecord'un taşıdığı her attribute. Bir record üzerindeki
#: bunların dışındaki her şey, uygulama tarafından sağlanan bir
#: `extra={...}` alanıdır ve JSON çıktısında yer almalıdır -- bu küme
#: olmadan, StructuredLoggingMiddleware'in extra alanları (method, path,
#: status, duration_ms, request_id) görünmez oluyor, yapılandırılmış
#: alanlar yerine `message` içine önceden biçimlendirilmiş bir f-string
#: olarak sessizce yutuluyordu.
_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JSONFormatter(logging.Formatter):
    """Logları son teknoloji, yapılandırılmış JSON formatında çıktılamak için özel formatter."""

    def format(self, record: logging.LogRecord) -> str:
        from app.api.middleware.correlation import get_request_id

        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "request_id": get_request_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_ATTRS and key not in log_data:
                log_data[key] = value

        # Varsa exception bilgisini ekle
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)

def setup_logging(environment: str = "development") -> None:
    """Sistem genelinde son teknoloji logging formatlarını yapılandırır.

    Production'da JSON formatlama, development'ta ise yapılandırılmış,
    renkli benzeri okunabilir loglar kullanır.
    """
    root_logger = logging.getLogger()

    # Yinelenen logları önlemek için mevcut handler'ları kaldır
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    
    if environment == "production":
        handler.setFormatter(JSONFormatter())
        root_logger.setLevel(logging.INFO)
    else:
        # Sade ve okunaklı development formatı
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        root_logger.setLevel(logging.DEBUG)
        
    root_logger.addHandler(handler)
    
    # Development'ta üçüncü parti kütüphanelerin ayrıntılı loglarını sustur
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
