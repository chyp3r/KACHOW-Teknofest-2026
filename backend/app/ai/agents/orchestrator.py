from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent responsible for coordinating workflows and delegating tasks to other agents."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="OrchestratorAgent",
            description="Coordinates multi-agent workflows, plans steps, and delegates tasks.",
            system_prompt=(
                "You are the Orchestrator Agent. Your role is to analyze the user's high-level request, "
                "break it down into logical steps, and coordinate with other specialized agents "
                "(NER, Classifier, Metadata, Writer, Editor, Verifier, Router) to achieve the goal."
            ),
        )
