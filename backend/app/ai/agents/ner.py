from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class NERAgent(BaseAgent):
    """Named Entity Recognition (NER) Agent responsible for extracting entities (names, organizations, locations, etc.) from text."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("ner")
        super().__init__(
            llm_client=llm_client,
            name="NERAgent",
            description="Extracts named entities such as people, organizations, dates, and locations from text.",
            system_prompt=system_prompt,
        )
