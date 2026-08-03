"""Registers listeners on the process-wide event bus.

``DocumentService``/``DraftService`` already publish ``DocumentUploadedEvent``
and ``DocumentAnalyzedEvent``, but nothing ever subscribed to them -- the bus
was write-only. Importing this module (see ``app.lifespan``) registers the
first listener so those publishes have an effect.
"""

import logging

from app.events.event import DocumentAnalyzedEvent
from app.events.subscriber import subscribe

logger = logging.getLogger(__name__)


@subscribe("document.analyzed")
async def _log_document_analyzed(event: DocumentAnalyzedEvent) -> None:
    """Structured log line for every completed Görev 1 analysis.

    A stand-in for a real downstream consumer (a search index, an audit
    trail, a Prometheus counter labelled by document_type) -- the point here
    is that the event now reaches at least one listener, not what that
    listener does.
    """
    logger.info(
        "document_analyzed",
        extra={
            "file_name": event.payload.get("file_name"),
            "document_type": event.payload.get("document_type"),
            "compliance_status": event.payload.get("compliance_status"),
            "missing_field_count": event.payload.get("missing_field_count"),
        },
    )
