from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class EvaluatorAgent(BaseAgent):
    """Evaluator Agent responsible for final quality assessment, grading, and scoring of document drafts."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("evaluator")
        super().__init__(
            llm_client=llm_client,
            name="EvaluatorAgent",
            description=(
                "Performs final quality control, grading correctness, structure, "
                "and assigns a confidence score to documents."
            ),
            system_prompt=system_prompt,
        )
