from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class VerifierAgent(BaseAgent):
    """Verifier Agent responsible for checking compliance, factual accuracy, safety, and guardrail validations."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("verifier")
        super().__init__(
            llm_client=llm_client,
            name="VerifierAgent",
            description="Verifies output accuracy, checks facts, checks compliance, and executes safety guardrails.",
            system_prompt=system_prompt,
        )
