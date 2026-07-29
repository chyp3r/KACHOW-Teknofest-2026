from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class ReflectionAgent(BaseAgent):
    """Reflection Agent responsible for critiquing, self-correcting, and refining document drafts."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("reflection")
        super().__init__(
            llm_client=llm_client,
            name="ReflectionAgent",
            description=(
                "Critiques generated document drafts to identify gaps, repetition, and quality issues, "
                "producing a refined and polished version."
            ),
            system_prompt=system_prompt,
        )
