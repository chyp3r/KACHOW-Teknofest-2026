import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager

logger = logging.getLogger(__name__)


class DocumentQAAgent(BaseAgent):
    """Answers user questions grounded in retrieved document context."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Initialize the Document QA agent.

        Args:
            llm_client: The LLM provider client.
            prompt_manager: Optional prompt manager override.
        """
        manager = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="DocumentQAAgent",
            description="Answers questions based on retrieved document context.",
            system_prompt=manager.get_template("document_qa"),
        )

    @staticmethod
    def _build(
        context: Optional[str],
        query: Optional[str],
        history: List[Dict[str, str]],
        history_summary: Optional[str] = None,
    ) -> tuple[List[Dict[str, str]], Dict[str, str]]:
        """Assemble the message list and prompt context for a QA turn.

        The question is sent as a real user turn rather than being buried in the
        system prompt. A chat model given only a system message has no turn to
        answer and several Ollama chat templates return an empty completion.

        Args:
            context: Retrieved document chunks joined into one string.
            query: The user's question.
            history: Prior conversation turns.
            history_summary: Rolling summary of turns older than the verbatim
                window, rendered as a block separate from the document context
                so the model never mistakes conversation memory for document
                content.

        Returns:
            The message list and the system-prompt render context.
        """
        messages = list(history)
        messages.append({"role": "user", "content": query or ""})
        return messages, {
            "context": context or "Bağlam bulunamadı.",
            "history_summary": history_summary
            or "(Bu konuşmada henüz özetlenecek eski mesaj yok.)",
        }

    async def answer(
        self,
        *,
        context: Optional[str] = None,
        query: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        history_summary: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Answer a question from the supplied document context.

        Args:
            context: Retrieved document chunks as a single string.
            query: The user's question.
            history: Optional prior conversation turns.
            history_summary: Rolling summary of turns older than the verbatim
                window.
            **kwargs: Extra provider configuration.

        Returns:
            The agent's answer.
        """
        messages, prompt_context = self._build(context, query, history or [], history_summary)
        return await self.run(
            messages=messages, context=prompt_context, temperature=0.2, **kwargs
        )

    def answer_stream(
        self,
        *,
        context: Optional[str] = None,
        query: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        history_summary: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream the answer token-by-token.

        Args:
            context: Retrieved document chunks as a single string.
            query: The user's question.
            history: Optional prior conversation turns.
            history_summary: Rolling summary of turns older than the verbatim
                window.
            **kwargs: Extra provider configuration.

        Returns:
            An async iterator of text chunks.
        """
        messages, prompt_context = self._build(context, query, history or [], history_summary)
        return self.stream(
            messages=messages, context=prompt_context, temperature=0.2, **kwargs
        )

    async def _execute(
        self,
        *,
        messages: List[Dict[str, str]],
        context: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Backwards-compatible alias for :meth:`answer`.

        Args:
            messages: Conversation history.
            context: Retrieved document chunks.
            query: The user's question.
            **kwargs: Extra provider configuration.

        Returns:
            The agent's answer.
        """
        return await self.answer(
            context=context, query=query, history=messages, **kwargs
        )
