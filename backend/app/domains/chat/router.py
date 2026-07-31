import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.dependency import get_chat_service
from app.api.responses import SuccessResponse
from app.domains.chat.chat_service import ChatService
from app.domains.chat.schema.chat_schema import ChatMessageRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def make_serializable(obj: Any) -> Any:
    """Recursively convert workflow output into JSON-serializable values.

    Workflow state carries LangChain ``Document`` objects and Pydantic models
    that ``json.dumps`` cannot encode, and a single unencodable value anywhere in
    the tree would abort the whole SSE stream.

    Args:
        obj: Any value from the workflow state.

    Returns:
        An equivalent structure of JSON-safe primitives.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): make_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_serializable(item) for item in obj]
    if hasattr(obj, "page_content") and hasattr(obj, "metadata"):
        return {
            "page_content": obj.page_content,
            "metadata": make_serializable(obj.metadata),
        }
    if hasattr(obj, "model_dump"):
        try:
            return make_serializable(obj.model_dump(mode="json"))
        except Exception:
            return make_serializable(obj.model_dump())
    return str(obj)


@router.post("/message", response_model=None)
async def send_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
):
    """Orchestrate a chat interaction and return the completed result.

    Routes the user input through the master planning graph, which resolves
    whether it needs analysis, drafting, document Q&A or plain conversation.
    """
    result = await service.handle_message(request)
    return SuccessResponse(data=make_serializable(result.model_dump()))


@router.post("/stream")
async def stream_chat_message(
    request: ChatMessageRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
):
    """Orchestrate a chat interaction and stream progress events over SSE.

    Emits ``node_start``/``node_end`` for workflow phases, ``token`` for live
    text as it is generated, ``partial_result`` for intermediate output the
    client can render before the run finishes, and one final ``final_result``.
    """

    async def event_generator():
        try:
            async for event in service.handle_message_stream(request):
                # Stop the workflow as soon as the client goes away instead of
                # holding the local model busy for a response nobody will read.
                if await http_request.is_disconnected():
                    logger.info("Client disconnected; aborting chat stream.")
                    break
                payload = json.dumps(make_serializable(event), ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("Chat stream failed")
            error = json.dumps(
                {"event": "error", "message": "Akış sırasında bir hata oluştu."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx buffers proxied responses by default, which would defeat the
            # entire point of streaming.
            "X-Accel-Buffering": "no",
        },
    )
