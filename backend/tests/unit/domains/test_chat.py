import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.chat.chat_service import ChatService
from app.domains.chat.schema.chat_schema import ChatMessageRequest

@pytest.fixture
def mock_planning_graph():
    graph = AsyncMock()
    return graph

@pytest.fixture
def chat_service(mock_planning_graph):
    return ChatService(planning_graph=mock_planning_graph)

@pytest.mark.asyncio
async def test_chat_service_plain_chat(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Merhaba", session_id="123")
    
    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "chat": {"reply": "Merhaba, size nasıl yardımcı olabilirim?"}
        }
    }
    
    response = await chat_service.handle_message(request)
    
    assert response.workflow_status == "COMPLETED"
    assert response.reply == "Merhaba, size nasıl yardımcı olabilirim?"
    mock_planning_graph.ainvoke.assert_called_once()

@pytest.mark.asyncio
async def test_chat_service_document_qa(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Bu belgede ne diyor?", document_id="doc_123")
    
    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "document_qa": {"reply": "Belge kuralları anlatıyor."}
        }
    }
    
    response = await chat_service.handle_message(request)
    
    assert response.workflow_status == "COMPLETED"
    assert response.reply == "Belge kuralları anlatıyor."
    
@pytest.mark.asyncio
async def test_chat_service_draft(chat_service, mock_planning_graph):
    request = ChatMessageRequest(message="Bana taslak yaz")
    
    mock_planning_graph.ainvoke.return_value = {
        "final_output": {
            "status": "COMPLETED",
            "draft": {"draft": "Bu bir resmi taslaktır."}
        }
    }
    
    response = await chat_service.handle_message(request)
    
    assert response.workflow_status == "COMPLETED"
    assert "Bu bir resmi taslaktır." in response.reply
