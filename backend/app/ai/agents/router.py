from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class RouterAgent(BaseAgent):
    """Router Agent responsible for deciding the best agent, tool, or workflow path to handle a given request."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="RouterAgent",
            description="Analyzes input requests and routes them to the most suitable specialized agent or workflow.",
            system_prompt=(
                "You are the Router Agent. Your role is to evaluate incoming queries or requests and determine "
                "which specialized agent (Orchestrator, NER, Classifier, Metadata, Writer, Editor, Verifier) "
                "or workflow should handle the request next."
            ),
        )
