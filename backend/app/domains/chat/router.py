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
