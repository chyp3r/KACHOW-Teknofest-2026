from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class ReviserAgent(BaseAgent):
    """Applies a numbered defect list to a previously generated draft.

    A separate class from WriterAgent so the "fix only what's listed, invent
    nothing" constraint is a system-level prompt rather than a user-turn
    suggestion the model can deprioritise.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="ReviserAgent",
            description="Repairs a draft's listed defects without regenerating it from scratch.",
            system_prompt=pm.get_template("reviser"),
            validators=[assert_no_prompt_leak],
        )
