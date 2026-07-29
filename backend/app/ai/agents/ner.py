from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class NERAgent(BaseAgent):
    """Named Entity Recognition (NER) Agent responsible for extracting entities (names, organizations, locations, etc.) from text."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="NERAgent",
            description="Extracts named entities such as people, organizations, dates, and locations from text.",
            system_prompt=(
                "You are the Named Entity Recognition (NER) Agent. Your role is to analyze the provided text, "
                "identify named entities (e.g., Person, Organization, Location, Date, Money), and return them "
                "clearly in a structured format."
            ),
        )
