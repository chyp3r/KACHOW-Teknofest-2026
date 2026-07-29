import json
import logging
from typing import Any, Dict, List, Optional

from app.ai.llms.base import BaseLLMClient
from app.ai.memory.base import BaseMemory
from app.infrastructure.cache.redis import RedisCache

logger = logging.getLogger(__name__)


class SummaryMemory(BaseMemory):
    """Long-term conversation memory that automatically compresses older conversation

    history into a concise summary using an LLM, keeping context window clean.
    """

    def __init__(
        self,
        cache_client: RedisCache,
        llm_client: BaseLLMClient,
        summary_threshold: int = 12,
        keep_last_k: int = 4,
    ):
        """Initialize Summary Memory.

        Args:
            cache_client: RedisCache client to store messages and summary.
            llm_client: BaseLLMClient provider to generate the summaries.
            summary_threshold: Trigger summarization once message count reaches this value.
            keep_last_k: Number of recent messages to preserve in raw format after summarizing.
        """
        self.cache = cache_client
        self.llm = llm_client
        self.summary_threshold = summary_threshold
        self.keep_last_k = keep_last_k
        logger.info(
            f"Initialized SummaryMemory with threshold={summary_threshold}, keep_last_k={keep_last_k}"
        )

    def _msg_key(self, session_id: str) -> str:
        """Redis key for raw messages."""
        return f"chat_memory:summary_msgs:{session_id}"

    def _sum_key(self, session_id: str) -> str:
        """Redis key for the accumulated summary string."""
        return f"chat_memory:summary_val:{session_id}"

    async def get_summary(self, session_id: str) -> str:
        """Retrieve the current accumulated summary from Redis cache."""
        key = self._sum_key(session_id)
        val = await self.cache.get(key)
        return val or ""

    async def get_messages(self, session_id: str, **kwargs) -> List[Dict[str, str]]:
        """Retrieve conversation history prefixed with the summary as a system message."""
        msg_key = self._msg_key(session_id)
        raw_data = await self.cache.get(msg_key)
        messages = []
        if raw_data:
            try:
                messages = json.loads(raw_data)
            except Exception as e:
                logger.error(f"Failed to parse summary messages: {e}")

        summary = await self.get_summary(session_id)
        if summary:
            # Inject the summarized context at the start of the stream
            context_msg = {
                "role": "system",
                "content": f"Geçmiş Konuşma Özeti:\n\"\"\"\n{summary}\n\"\"\"",
            }
            return [context_msg] + messages
        return messages

    async def add_message(
        self, session_id: str, role: str, content: str, **kwargs
    ) -> None:
        """Add new message, trigger summarization if threshold is hit, and prune list."""
        msg_key = self._msg_key(session_id)
        raw_data = await self.cache.get(msg_key)
        messages = []
        if raw_data:
            try:
                messages = json.loads(raw_data)
            except Exception:
                pass

        messages.append({"role": role, "content": content})

        # Trigger compression if threshold reached
        if len(messages) >= self.summary_threshold:
            logger.info(
                f"Summary threshold ({self.summary_threshold}) hit for session {session_id}. Compressing..."
            )
            await self._summarize(session_id, messages)
            # Prune to keep only the latest K messages
            messages = messages[-self.keep_last_k :]

        await self.cache.set(msg_key, json.dumps(messages))

    async def _summarize(
        self, session_id: str, messages: List[Dict[str, str]]
    ) -> None:
        """Generate a combined summary using the LLM client."""
        existing_summary = await self.get_summary(session_id)

        # Build raw string representation of chat turns
        formatted_history = "\n".join(
            [f"{m['role'].upper()}: {m['content']}" for m in messages]
        )

        prompt = (
            "Sen profesyonel bir sohbet özetleyici ajansın. Görevin, aşağıdaki sohbet akışını "
            "ve varsa önceki sohbet özetini birleştirerek güncel bir özet çıkarmaktır.\n\n"
            f"Önceki Özet: \"{existing_summary}\"\n\n"
            f"Yeni Sohbet Akışı:\n\"\"\"\n{formatted_history}\n\"\"\"\n\n"
            "Lütfen önceki özetteki önemli bilgileri kaybetmeden ve yeni akışı da kapsayacak şekilde "
            "özlü, net ve tamamen olgulara dayalı güncel bir Türkçe özet oluştur."
        )

        try:
            # Generate new summary using default model
            summary = await self.llm.generate(
                [{"role": "user", "content": prompt}], temperature=0.3
            )
            sum_key = self._sum_key(session_id)
            await self.cache.set(sum_key, summary.strip())
            logger.info(
                f"Successfully updated summary value for session: {session_id}"
            )
        except Exception as e:
            logger.error(
                f"SummaryMemory failed to generate LLM summary: {e}",
                exc_info=True,
            )

    async def clear(self, session_id: str) -> None:
        """Clear all messages and summaries for this session."""
        await self.cache.delete(self._msg_key(session_id))
        await self.cache.delete(self._sum_key(session_id))
        logger.debug(f"Cleared SummaryMemory for session: {session_id}")
