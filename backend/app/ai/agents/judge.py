from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class JudgeAgent(BaseAgent):
    """Judges a draft on criteria the deterministic verifier cannot check.

    Runs on the fast tier: it emits a small structured verdict, never the
    draft text itself, so its cost is a label-sized generation rather than a
    second full draft.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="JudgeAgent",
            description=(
                "Judges a draft's request-fit, register, closing direction and "
                "muhatap consistency -- the parts of quality a regex cannot see."
            ),
            system_prompt=pm.get_template("judge"),
        )
