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


@pytest.mark.asyncio
async def test_answer_never_leaves_a_literal_history_summary_placeholder(
    document_qa_agent, mock_llm_client
):
    """history_summary omitted entirely must still render (default filler
    text), never leak `{{history_summary}}` verbatim into the system prompt
    sent to the model."""
    await document_qa_agent.answer(context="Bağlam.", query="Soru?")

    system_prompt = mock_llm_client.generate.call_args.kwargs["messages"][0]["content"]
    assert "{{history_summary}}" not in system_prompt
    assert "{{context}}" not in system_prompt


@pytest.mark.asyncio
async def test_answer_renders_a_supplied_history_summary(document_qa_agent, mock_llm_client):
    await document_qa_agent.answer(
        context="Bağlam.", query="Az önce ne sordum?", history_summary="Kullanıcı X hakkında sordu."
    )

    system_prompt = mock_llm_client.generate.call_args.kwargs["messages"][0]["content"]
    assert "Kullanıcı X hakkında sordu." in system_prompt
