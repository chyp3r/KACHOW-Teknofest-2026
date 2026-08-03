import json
import logging
import sys
from datetime import datetime, timezone

#: Every attribute a stock LogRecord carries. Anything else on a record is an
#: application-supplied `extra={...}` field and belongs in the JSON output --
#: without this set, StructuredLoggingMiddleware's extras (method, path,
#: status, duration_ms, request_id) were invisible, silently absorbed into
#: `message` as a pre-formatted f-string instead of structured fields.
_STANDARD_LOG_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)


class JSONFormatter(logging.Formatter):
    """Custom formatter to output logs in SOTA structured JSON format."""

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

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)

def setup_logging(environment: str = "development") -> None:
    """Configure system-wide SOTA logging formats.
    
    Uses JSON formatting in production and structured colored-like readable logs in development.
    """
    root_logger = logging.getLogger()
    
    # Remove existing handlers to prevent duplicate logs
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    handler = logging.StreamHandler(sys.stdout)
    
    if environment == "production":
        handler.setFormatter(JSONFormatter())
        root_logger.setLevel(logging.INFO)
    else:
        # Beautiful clean development format
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        root_logger.setLevel(logging.DEBUG)
        
    root_logger.addHandler(handler)
    
    # Silence third-party library verbose logs in development
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
