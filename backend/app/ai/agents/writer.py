from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class WriterAgent(BaseAgent):
    """Writer Agent responsible for generating high-quality reports, summaries, articles, and text responses."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="WriterAgent",
            description="Generates text, reports, drafts, summaries, and structured written responses.",
            system_prompt=(
                "You are the Writer Agent. Your role is to produce high-quality, articulate, and well-structured "
                "written content, adapting your tone and style to the user's specific guidelines and objectives."
            ),
        )
