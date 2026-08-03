from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class WriterAgent(BaseAgent):
    """Writer Agent responsible for generating high-quality reports, summaries, articles, and text responses.

    ``validators`` here only guards a future ``.run()``/``.run_structured()``
    call -- ``draft_graph.writer_node`` uses ``.stream()``, which cannot
    validate before emission, so the actual guard on the accumulated draft
    text lives in that node.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or get_prompt_manager()
        system_prompt = pm.get_template("writer")
        super().__init__(
            llm_client=llm_client,
            name="WriterAgent",
            description="Generates text, reports, drafts, summaries, and structured written responses.",
            system_prompt=system_prompt,
            validators=[assert_no_prompt_leak],
        )
