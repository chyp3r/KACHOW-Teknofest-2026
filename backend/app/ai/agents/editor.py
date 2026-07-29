from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager


class EditorAgent(BaseAgent):
    """Editor Agent responsible for proofreading, refining style, correcting grammar, and editing written output."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or PromptManager()
        system_prompt = pm.get_template("editor")
        super().__init__(
            llm_client=llm_client,
            name="EditorAgent",
            description="Reviews, edits, proofreads, and improves the quality, flow, and formatting of text.",
            system_prompt=system_prompt,
        )
