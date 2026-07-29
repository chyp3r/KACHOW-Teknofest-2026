from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient


class EditorAgent(BaseAgent):
    """Editor Agent responsible for proofreading, refining style, correcting grammar, and editing written output."""

    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            name="EditorAgent",
            description="Reviews, edits, proofreads, and improves the quality, flow, and formatting of text.",
            system_prompt=(
                "You are the Editor Agent. Your role is to review content produced by the Writer Agent or user inputs, "
                "correcting grammar, improving sentence flow, refining tone, and ensuring high-quality final drafts."
            ),
        )
