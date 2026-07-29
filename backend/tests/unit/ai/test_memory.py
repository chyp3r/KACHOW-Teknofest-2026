import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.ai.memory import (
    ConversationWindowMemory,
    SummaryMemory,
    VectorMemory,
)
from app.infrastructure.cache.redis import RedisCache
from app.ai.llms.base import BaseLLMClient
from app.ai.agents.base import BaseAgent
from app.ai.memory.vector_memory import MemoryFact


# ==========================================
# Conversation Window Memory Tests
# ==========================================
@pytest.mark.asyncio
async def test_conversation_window_memory():
    mock_redis = MagicMock(spec=RedisCache)
    
    # Mock Redis storage using local dict
    storage = {}
    async def mock_get(key):
        return storage.get(key)
    async def mock_set(key, value, *args, **kwargs):
        storage[key] = value
        return True

    mock_redis.get = mock_get
    mock_redis.set = mock_set

    # Instantiate window memory with size 3
    memory = ConversationWindowMemory(cache_client=mock_redis, window_size=3)
    session_id = "test_session_1"

    # Add 4 messages (should prune the 1st one)
    await memory.add_message(session_id, "user", "msg1")
    await memory.add_message(session_id, "assistant", "msg2")
    await memory.add_message(session_id, "user", "msg3")
    await memory.add_message(session_id, "assistant", "msg4")

    messages = await memory.get_messages(session_id)
    
    assert len(messages) == 3
    assert messages[0]["content"] == "msg2"
    assert messages[1]["content"] == "msg3"
    assert messages[2]["content"] == "msg4"


# ==========================================
# Summary Memory Tests
# ==========================================
@pytest.mark.asyncio
async def test_summary_memory_trigger():
    mock_redis = MagicMock(spec=RedisCache)
    storage = {}
    async def mock_get(key):
        return storage.get(key)
    async def mock_set(key, value, *args, **kwargs):
        storage[key] = value
        return True

    mock_redis.get = mock_get
    mock_redis.set = mock_set

    # Mock LLM Client
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_llm.generate = AsyncMock(return_value="Updated conversation summary.")

    # Threshold = 3, Keep = 1
    memory = SummaryMemory(
        cache_client=mock_redis,
        llm_client=mock_llm,
        summary_threshold=3,
        keep_last_k=1
    )
    session_id = "test_session_2"

    # Add 2 messages (no trigger)
    await memory.add_message(session_id, "user", "hello")
    await memory.add_message(session_id, "assistant", "hi")
    
    msgs = await memory.get_messages(session_id)
    # No summary generated yet
    assert len(msgs) == 2

    # Add 3rd message (triggers summary!)
    await memory.add_message(session_id, "user", "how are you?")
    
    # Get messages should return: [System summary message, 3rd message (pruned keep_last_k=1)]
    final_msgs = await memory.get_messages(session_id)
    assert len(final_msgs) == 2
    assert final_msgs[0]["role"] == "system"
    assert "Updated conversation summary." in final_msgs[0]["content"]
    assert final_msgs[1]["content"] == "how are you?"
    mock_llm.generate.assert_called_once()


# ==========================================
# Vector Memory (Mem0-like) Tests
# ==========================================
@pytest.mark.asyncio
async def test_vector_memory_turn_extraction():
    mock_vector_store = AsyncMock()
    
    # Mock Embeddings client
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])

    # Mock Agent structured return
    mock_agent = MagicMock(spec=BaseAgent)
    mock_agent_response = MemoryFact(
        facts=["User prefers Python", "User is building KACHOW project"]
    )
    mock_agent.run_structured = AsyncMock(return_value=mock_agent_response)

    # Instantiate VectorMemory (Mem0-like)
    vector_memory = VectorMemory(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        agent=mock_agent,
        collection_name="test_facts"
    )
    session_id = "test_session_3"

    # Add turn
    extracted_facts = await vector_memory.add_conversation_turn(
        session_id=session_id,
        user_message="I like python and KACHOW is my NLP project",
        assistant_message="Got it! Python and KACHOW NLP."
    )

    # Verify facts extracted
    assert len(extracted_facts) == 2
    assert "User prefers Python" in extracted_facts
    assert "User is building KACHOW project" in extracted_facts

    # Verify collection created and documents upserted
    mock_vector_store.create_collection.assert_called_once_with(
        collection_name="test_facts", vector_size=3
    )
    mock_vector_store.upsert_documents.assert_called_once()


@pytest.mark.asyncio
async def test_vector_memory_retrieve():
    mock_vector_store = AsyncMock()
    mock_hit = {"text": "User likes Python", "score": 0.98, "metadata": {}}
    mock_vector_store.similarity_search.return_value = [mock_hit]

    mock_embeddings = MagicMock()
    mock_embeddings.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    
    mock_agent = MagicMock(spec=BaseAgent)

    vector_memory = VectorMemory(
        vector_store=mock_vector_store,
        embeddings_client=mock_embeddings,
        agent=mock_agent,
        collection_name="test_facts"
    )

    # Search
    relevant = await vector_memory.get_relevant_facts("What programming languages does the user use?")
    
    assert len(relevant) == 1
    assert relevant[0] == "User likes Python"
    mock_vector_store.similarity_search.assert_called_once()
