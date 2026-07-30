import logging
from typing import Any, Dict, List, Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager

logger = logging.getLogger(__name__)


class DocumentQAAgent(BaseAgent):
    """An agent that answers user questions based on a retrieved document context."""

    def __init__(self, llm_client: BaseLLMClient):
        self.prompt_manager = PromptManager()
        self.system_prompt_template = self.prompt_manager.get_template("document_qa")
        
        super().__init__(
            llm_client=llm_client, 
            name="document_qa",
            description="Answers questions based on retrieved document context.",
            system_prompt=self.system_prompt_template
        )

    async def _execute(
        self,
        *,
        messages: List[Dict[str, str]],
        context: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Execute the Document QA agent.

        Args:
            messages: Conversation history.
            context: Retrieved document chunks as a single string.
            query: The user's question.

        Returns:
            The agent's answer.
        """
        # Format the system prompt with context and query
        formatted_system_prompt = self.system_prompt_template.format(
            context=context or "Bağlam bulunamadı.",
            query=query or "",
        )

        llm_messages = [{"role": "system", "content": formatted_system_prompt}]
        llm_messages.extend(messages)

        logger.info(f"Running {self.name} Agent...")
        try:
            return await self.llm_client.generate(llm_messages, **kwargs)
        except Exception as e:
            logger.error(f"{self.name} Agent execution failed: {e}")
            raise
