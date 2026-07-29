import json
import logging
from typing import Any, Dict, List

from app.ai.memory.base import BaseMemory
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)


class ConversationWindowMemory(BaseMemory):
    """Short-term, window-based conversation memory backed by Redis.

    Limits stored messages to the latest N turns to optimize LLM context usage.
    """

    def __init__(self, cache_client: RedisCache, window_size: int = 10):
        """Initialize Conversation Window Memory.

        Args:
            cache_client: An instance of RedisCache to store message history.
            window_size: Maximum number of recent messages to keep.
        """
        self.cache = cache_client
        self.window_size = window_size
        logger.info(
            f"Initialized ConversationWindowMemory with window_size={window_size}"
        )

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for session history."""
        return f"chat_memory:window:{session_id}"

    async def get_messages(self, session_id: str, **kwargs) -> List[Dict[str, str]]:
        """Retrieve conversation history for a session."""
        key = self._session_key(session_id)
        raw_data = await self.cache.get(key)
        if not raw_data:
            return []

        try:
            return json.loads(raw_data)
        except Exception as e:
            logger.error(
                f"Failed to parse chat memory JSON for session {session_id}: {e}"
            )
            return []

    async def add_message(
        self, session_id: str, role: str, content: str, **kwargs
    ) -> None:
        """Add message to history and prune oldest if window size exceeded."""
        messages = await self.get_messages(session_id)
        messages.append({"role": role, "content": content})

        # Apply sliding window: keep only the latest N messages
        if len(messages) > self.window_size:
            messages = messages[-self.window_size :]

        key = self._session_key(session_id)
        await self.cache.set(key, json.dumps(messages))

    async def clear(self, session_id: str) -> None:
        """Delete session history from Redis cache."""
        key = self._session_key(session_id)
        await self.cache.delete(key)
        logger.debug(f"Cleared ConversationWindowMemory for session: {session_id}")
