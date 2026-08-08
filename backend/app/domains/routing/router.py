import asyncio
import logging

from fastapi import APIRouter, Depends

from app.api.dependency import get_routing_graph, require_auth_if_enabled
from app.api.exceptions.ai_error import AIException
from app.api.responses import SuccessResponse
from app.core.config import settings
from app.domains.routing.schema import RoutingSuggestionRequest, RoutingSuggestionResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/routing", tags=["routing"], dependencies=[Depends(require_auth_if_enabled)]
)


@router.post("/suggest", response_model=None)
async def suggest_routing(
    request: RoutingSuggestionRequest,
    routing_graph=Depends(get_routing_graph),
):
    """Produce a unit-routing decision for a draft, independent of drafting it.

    Standalone from ``POST /documents/draft`` so a human who edits a draft
    after it was generated can get a fresh routing decision without paying
    for a new generation -- the routing graph runs on the fast tier and reads
    only the draft text and its confidence score.
    """
    try:
        state = await asyncio.wait_for(
            routing_graph.ainvoke(
                {"draft": request.draft, "confidence_score": request.confidence_score}
            ),
            timeout=settings.AI_WORKFLOW_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise AIException(
            message="Yönlendirme kararı zaman aşımına uğradı.",
            details={"timeout_seconds": settings.AI_WORKFLOW_TIMEOUT_SECONDS},
        ) from exc
    except Exception as exc:
        logger.exception("Standalone routing suggestion failed")
        raise AIException(
            message="Yönlendirme sırasında bir hata oluştu.", details={"reason": str(exc)}
        ) from exc

    response = RoutingSuggestionResponse(
        routed_unit=state.get("routed_unit", "İnsan Onayı Gerekli"),
        priority=state.get("priority", "Normal"),
        reasoning=state.get("reasoning", ""),
        justification=state.get("justification", state.get("reasoning", "")),
    )
    return SuccessResponse(data=response.model_dump())
