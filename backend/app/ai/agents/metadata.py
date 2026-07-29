from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class MetadataAgent(BaseAgent):
    """Metadata Agent responsible for extracting document attributes, summaries, keywords, and structural information."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="MetadataAgent",
            description="Extracts metadata, keywords, file details, and structural properties from documents.",
            system_prompt=(
                "You are the Metadata Agent. Your role is to analyze documents or text inputs, "
                "extract relevant metadata (such as authors, topics, keywords, creation dates, summaries), "
                "and organize them in a clean, structured output."
            ),
        )
