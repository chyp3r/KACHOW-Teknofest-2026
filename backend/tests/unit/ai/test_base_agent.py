from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from pydantic import BaseModel

from app.ai.agents import (
    BaseAgent,
    OrchestratorAgent,
    NERAgent,
    ClassifierAgent,
    MetadataAgent,
    WriterAgent,
    EditorAgent,
    VerifierAgent,
    RouterAgent,
)


class DummySchema(BaseModel):
    key: str
    value: int


@pytest.fixture
def mock_llm_client():
    return MagicMock()


def test_base_agent_initialization(mock_llm_client):
    agent = OrchestratorAgent(llm_client=mock_llm_client)
    assert agent.name == "OrchestratorAgent"
    assert agent.llm_client == mock_llm_client
    assert "Coordinates" in agent.description


def test_base_agent_prompt_rendering(mock_llm_client):
    agent = BaseAgent(
        llm_client=mock_llm_client,
        name="TestAgent",
        description="A test agent",
        system_prompt="Hello {name}, welcome to {project}!",
    )

    # Render without context
    assert agent._render_system_prompt() == "Hello {name}, welcome to {project}!"

    # Render with context
    ctx = {"name": "Gökdeniz", "project": "KACHOW"}
    assert agent._render_system_prompt(ctx) == "Hello Gökdeniz, welcome to KACHOW!"

    # Render with missing keys (should fail gracefully and log warning)
    bad_ctx = {"name": "Gökdeniz"}
    assert (
        agent._render_system_prompt(bad_ctx)
        == "Hello {name}, welcome to {project}!"
    )


@pytest.mark.asyncio
async def test_base_agent_run_success(mock_llm_client):
    mock_llm_client.generate = AsyncMock(return_value="Agent response text")

    agent = BaseAgent(
        llm_client=mock_llm_client,
        name="TestAgent",
        description="A test agent",
        system_prompt="You are a helper.",
    )

    response = await agent.run(messages="Hello", temperature=0.5)

    assert response == "Agent response text"
    mock_llm_client.generate.assert_called_once_with(
        messages=[
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Hello"},
        ],
        temperature=0.5,
        max_tokens=None,
    )


@pytest.mark.asyncio
async def test_base_agent_run_structured_success(mock_llm_client):
    expected_output = DummySchema(key="score", value=95)
    mock_llm_client.generate_structured = AsyncMock(
        return_value=expected_output
    )

    agent = BaseAgent(
        llm_client=mock_llm_client,
        name="TestAgent",
        description="A test agent",
        system_prompt="Output structured data.",
    )

    result = await agent.run_structured(
        messages="Input data", response_model=DummySchema, temperature=0.1
    )

    assert result.key == "score"
    assert result.value == 95
    mock_llm_client.generate_structured.assert_called_once()


@pytest.mark.asyncio
async def test_base_agent_run_structured_retry_loop(mock_llm_client):
    expected_output = DummySchema(key="retry_success", value=100)

    # Fail on first attempt, succeed on second attempt
    mock_llm_client.generate_structured = AsyncMock(
        side_effect=[ValueError("Invalid schema structure"), expected_output]
    )

    agent = BaseAgent(
        llm_client=mock_llm_client,
        name="TestAgent",
        description="A test agent",
        system_prompt="Output structured data.",
    )

    result = await agent.run_structured(
        messages="Input data", response_model=DummySchema, max_retries=2
    )

    assert result.key == "retry_success"
    assert result.value == 100
    # generate_structured should be called twice (initial + 1 retry)
    assert mock_llm_client.generate_structured.call_count == 2


def test_specialist_agents_inheritance(mock_llm_client):
    agents = [
        OrchestratorAgent(mock_llm_client),
        NERAgent(mock_llm_client),
        ClassifierAgent(mock_llm_client),
        MetadataAgent(mock_llm_client),
        WriterAgent(mock_llm_client),
        EditorAgent(mock_llm_client),
        VerifierAgent(mock_llm_client),
        RouterAgent(mock_llm_client),
    ]

    for agent in agents:
        assert isinstance(agent, BaseAgent)
        assert agent.llm_client == mock_llm_client
        assert agent.name is not None
        assert agent.system_prompt is not None
