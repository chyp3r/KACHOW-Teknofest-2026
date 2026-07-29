from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class RouterAgent(BaseAgent):
    """Router Agent responsible for deciding the best agent, tool, or workflow path to handle a given request."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("router")
        super().__init__(
            llm_client=llm_client,
            name="RouterAgent",
            description="Analyzes input requests and routes them to the most suitable specialized agent or workflow.",
            system_prompt=system_prompt,
        )
