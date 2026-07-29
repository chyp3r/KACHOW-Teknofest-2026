from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class ClassifierAgent(BaseAgent):
    """Classifier Agent responsible for classifying texts, categorizing requests, and analyzing sentiment."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="ClassifierAgent",
            description="Categorizes text into predefined categories, labels, and performs sentiment analysis.",
            system_prompt=(
                "You are the Classification Agent. Your role is to classify input texts or user requests "
                "into appropriate categories, assign labels, or determine sentiment, ensuring that classification "
                "is accurate and context-aware."
            ),
        )
