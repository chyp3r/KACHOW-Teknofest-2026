import pytest
from unittest.mock import AsyncMock

from app.ai.agents.document_qa import DocumentQAAgent
from app.ai.llms.base import BaseLLMClient

@pytest.fixture
def mock_llm_client():
    client = AsyncMock(spec=BaseLLMClient)
    client.generate.return_value = "Belgedeki bilgilere göre, süre 15 gündür."
    return client

@pytest.fixture
def document_qa_agent(mock_llm_client):
    return DocumentQAAgent(llm_client=mock_llm_client)

@pytest.mark.asyncio
async def test_document_qa_agent_execution(document_qa_agent, mock_llm_client):
    context = "Dilekçe hakkının kullanılmasında yasal süre 15 gündür."
    query = "Süre kaç gün?"
    
    response = await document_qa_agent._execute(messages=[], context=context, query=query)
    
    assert response == "Belgedeki bilgilere göre, süre 15 gündür."
    mock_llm_client.generate.assert_called_once()
