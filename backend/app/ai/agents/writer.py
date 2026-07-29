from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class WriterAgent(BaseAgent):
    """Writer Agent responsible for generating high-quality reports, summaries, articles, and text responses."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("writer")
        super().__init__(
            llm_client=llm_client,
            name="WriterAgent",
            description="Generates text, reports, drafts, summaries, and structured written responses.",
            system_prompt=system_prompt,
        )
