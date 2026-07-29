from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from pydantic import BaseModel

from app.ai.llms.ollama import OllamaClient
from langchain_core.messages import AIMessage


class UserSchema(BaseModel):
    name: str
    age: int


@pytest.mark.asyncio
@patch("app.ai.llms.ollama.ChatOllama")
async def test_ollama_generate(mock_chat_ollama):
    # Setup mock response
    mock_instance = MagicMock()
    mock_instance.ainvoke = AsyncMock(return_value=AIMessage(content="Hello! I am Qwen."))
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3.5:9b")
    messages = [{"role": "user", "content": "Hi"}]

    response = await client.generate(messages, temperature=0.5)

    assert response == "Hello! I am Qwen."
    mock_chat_ollama.assert_called_once_with(
        base_url="http://localhost:11434",
        model="qwen3.5:9b",
        temperature=0.5
    )


@pytest.mark.asyncio
@patch("app.ai.llms.ollama.ChatOllama")
async def test_ollama_stream(mock_chat_ollama):
    # Setup mock stream
    mock_instance = MagicMock()

    async def mock_astream(*args, **kwargs):
        yield AIMessage(content="Hello")
        yield AIMessage(content="!")

    mock_instance.astream = mock_astream
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3.5:9b")
    messages = [{"role": "user", "content": "Hi"}]

    chunks = []
    async for chunk in client.stream(messages):
        chunks.append(chunk)

    assert "".join(chunks) == "Hello!"


@pytest.mark.asyncio
@patch("app.ai.llms.ollama.ChatOllama")
async def test_ollama_generate_structured(mock_chat_ollama):
    # Setup mock structured output
    mock_instance = MagicMock()
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=UserSchema(name="Gökdeniz", age=25))
    mock_instance.with_structured_output.return_value = mock_structured_llm
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(base_url="http://localhost:11434", model="qwen3.5:9b")
    messages = [{"role": "user", "content": "Extract name and age"}]

    response = await client.generate_structured(messages, response_model=UserSchema)

    assert response.name == "Gökdeniz"
    assert response.age == 25
    mock_instance.with_structured_output.assert_called_once_with(UserSchema)
