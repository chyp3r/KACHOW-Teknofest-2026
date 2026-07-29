from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class VerifierAgent(BaseAgent):
    """Verifier Agent responsible for checking compliance, factual accuracy, safety, and guardrail validations."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="VerifierAgent",
            description="Verifies output accuracy, checks facts, checks compliance, and executes safety guardrails.",
            system_prompt=(
                "You are the Verifier Agent. Your role is to carefully audit responses and generated outputs "
                "to ensure they are factually correct, free from sensitive information, secure, and compliant "
                "with proscribed guardrails."
            ),
        )
