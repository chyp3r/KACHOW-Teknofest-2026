from fastapi import APIRouter, Depends
from app.api.responses import SuccessResponse
from app.api.dependency import get_chat_service
from app.domains.chat.chat_service import ChatService
from app.domains.chat.schema.chat_schema import ChatMessageRequest, ChatMessageResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/message", response_model=None)
async def send_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
):
    """Orchestrate a chat interaction (Task 3).
    
    Routes user input through the Master Planning Graph, resolving whether 
    it needs classification, RAG, drafting, or just a simple chat response.
    """
    result = await service.handle_message(request)
    return SuccessResponse(data=result.model_dump(mode="json"))


from fastapi.responses import StreamingResponse
import json
from typing import Any

def make_serializable(obj: Any) -> Any:
    """Recursively convert non-serializable objects (like LangChain Documents, Pydantic models) to JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(item) for item in obj]
    elif hasattr(obj, "page_content") and hasattr(obj, "metadata"):  # LangChain Document
        return {
            "page_content": obj.page_content,
            "metadata": obj.metadata
        }
    elif hasattr(obj, "model_dump"):  # Pydantic v2
        return make_serializable(obj.model_dump())
    elif hasattr(obj, "dict"):  # Pydantic v1
        return make_serializable(obj.dict())
    
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)

@router.post("/stream")
async def stream_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
):
    """Orchestrate a chat interaction and stream events (Task 3)."""
    async def event_generator():
        async for event in service.handle_message_stream(request):
            serializable_event = make_serializable(event)
            yield f"data: {json.dumps(serializable_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
