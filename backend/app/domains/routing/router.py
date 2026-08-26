import asyncio
import logging

from fastapi import APIRouter, Depends

from app.api.dependency import get_routing_graph, require_auth_if_enabled
from app.api.exceptions.ai_error import AIException
from app.api.responses import SuccessResponse
from app.core.config import settings
from app.domains.routing.schema import RoutingSuggestionRequest, RoutingSuggestionResponse
from app.domains.users.model.user_model import UserModel

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/routing", tags=["routing"], dependencies=[Depends(require_auth_if_enabled)]
)


@router.post("/suggest", response_model=None)
async def suggest_routing(
    request: RoutingSuggestionRequest,
    routing_graph=Depends(get_routing_graph),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir taslak için, taslağı oluşturmaktan bağımsız olarak birim yönlendirme kararı üretir.

    ``POST /documents/draft`` uç noktasından bağımsızdır; böylece bir taslak
    oluşturulduktan sonra onu düzenleyen bir kullanıcı, yeni bir üretim
    maliyetine katlanmadan güncel bir yönlendirme kararı alabilir -- yönlendirme
    grafiği hızlı katmanda çalışır ve yalnızca taslak metnini ve güven skorunu okur.
    """
    try:
        state = await asyncio.wait_for(
            routing_graph.ainvoke(
                {
                    "draft": request.draft,
                    "confidence_score": request.confidence_score,
                    "company_id": current_user.company_id,
                }
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
        routed_unit=state.get("routed_unit"),
        alternative_units=state.get("alternative_units") or [],
        priority=state.get("priority", "Normal"),
        reasoning=state.get("reasoning", ""),
        justification=state.get("justification", state.get("reasoning", "")),
        requires_human_approval=state.get("requires_human_approval", False),
    )
    return SuccessResponse(data=response.model_dump())
