from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class ComplianceAgent(BaseAgent):
    """Compliance Agent responsible for grounding documents in relevant legislation."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("compliance")
        super().__init__(
            llm_client=llm_client,
            name="ComplianceAgent",
            description=(
                "Matches incoming official documents against retrieved legislation "
                "and explains which rule each missing field relates to."
            ),
            system_prompt=system_prompt,
        )
