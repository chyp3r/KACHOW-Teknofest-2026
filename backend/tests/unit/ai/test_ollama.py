from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from app.ai.llms import get_llm_client
from app.core.config import settings
from app.infrastructure.providers.ollama import OllamaClient


class UserSchema(BaseModel):
    name: str
    age: int


@pytest.mark.asyncio
@patch("app.infrastructure.providers.ollama.ChatOllama")
async def test_ollama_generate(mock_chat_ollama):
    mock_instance = MagicMock()
    mock_instance.ainvoke = AsyncMock(
        return_value=AIMessage(content="Hello! I am Qwen.")
    )
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
    )
    messages = [{"role": "user", "content": "Hi"}]

    response = await client.generate(messages, temperature=0.5)

    assert response == "Hello! I am Qwen."
    mock_chat_ollama.assert_called_once_with(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
        temperature=0.5,
        reasoning=False,
        num_predict=1024,
    )


@pytest.mark.asyncio
@patch("app.infrastructure.providers.ollama.ChatOllama")
async def test_ollama_stream(mock_chat_ollama):
    mock_instance = MagicMock()

    async def mock_astream(*args, **kwargs):
        yield AIMessage(content="Hello")
        yield AIMessage(content="!")

    mock_instance.astream = mock_astream
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
    )
    messages = [{"role": "user", "content": "Hi"}]

    chunks = []
    async for chunk in client.stream(messages):
        chunks.append(chunk)

    assert "".join(chunks) == "Hello!"
    mock_chat_ollama.assert_called_once_with(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
        temperature=0.7,
        reasoning=False,
        num_predict=1024,
    )


@pytest.mark.asyncio
@patch("app.infrastructure.providers.ollama.ChatOllama")
async def test_ollama_generate_structured(mock_chat_ollama):
    mock_instance = MagicMock()
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(
        return_value=UserSchema(name="Gökdeniz", age=25)
    )
    mock_instance.with_structured_output.return_value = mock_structured_llm
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
    )
    messages = [{"role": "user", "content": "Extract name and age"}]

    response = await client.generate_structured(messages, response_model=UserSchema)

    assert response.name == "Gökdeniz"
    assert response.age == 25
    mock_instance.with_structured_output.assert_called_once_with(UserSchema)
    mock_chat_ollama.assert_called_once_with(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
        temperature=0.7,
        reasoning=False,
        num_predict=1024,
    )


@pytest.mark.asyncio
@patch("app.infrastructure.providers.ollama.ChatOllama")
async def test_ollama_generate_allows_runtime_overrides(mock_chat_ollama):
    mock_instance = MagicMock()
    mock_instance.ainvoke = AsyncMock(return_value=AIMessage(content="Override works"))
    mock_chat_ollama.return_value = mock_instance

    client = OllamaClient(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
    )

    response = await client.generate(
        [{"role": "user", "content": "Hi"}],
        max_tokens=128,
        reasoning=True,
    )

    assert response == "Override works"
    mock_chat_ollama.assert_called_once_with(
        base_url="http://localhost:11434",
        model="qwen3:4b-instruct-2507-q4_K_M",
        temperature=0.7,
        reasoning=True,
        num_predict=128,
    )


def test_ollama_factory_uses_local_defaults():
    client = get_llm_client()

    assert isinstance(client, OllamaClient)
    assert client.model_name == settings.OLLAMA_MODEL
    assert client.reasoning is False
    assert client.max_tokens == 1024
