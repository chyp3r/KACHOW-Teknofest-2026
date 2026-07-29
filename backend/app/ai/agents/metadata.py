from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class MetadataAgent(BaseAgent):
    """Metadata Agent responsible for extracting document attributes, summaries, keywords, and structural information."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("metadata")
        super().__init__(
            llm_client=llm_client,
            name="MetadataAgent",
            description="Extracts metadata, keywords, file details, and structural properties from documents.",
            system_prompt=system_prompt,
        )
