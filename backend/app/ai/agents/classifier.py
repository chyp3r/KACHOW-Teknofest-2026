from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class ClassifierAgent(BaseAgent):
    """Classifier Agent responsible for classifying texts, categorizing requests, and analyzing sentiment."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("classifier")
        super().__init__(
            llm_client=llm_client,
            name="ClassifierAgent",
            description="Categorizes text into predefined categories, labels, and performs sentiment analysis.",
            system_prompt=system_prompt,
        )
