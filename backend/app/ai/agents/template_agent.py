from typing import Callable, Optional, Sequence

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class TemplateAgent(BaseAgent):
    """An agent that is nothing more than a named prompt template.

    ``ClassifierAgent``, ``ComplianceAgent``, ``RouterAgent`` and
    ``JudgeAgent`` each reimplemented the same ``__init__`` (load a template
    by name, forward name/description/validators to ``BaseAgent``) with no
    other behavior of their own. They now subclass this and set the three
    class attributes below instead. Class name, module path and constructor
    signature are unchanged, so every existing call site and test keeps
    working -- several tests patch by dotted path (e.g.
    ``app.ai.agents.classifier.ClassifierAgent.run_structured``), which a
    single shared class replacing all four would have broken.
    """

    #: Template name in prompts/templates/, e.g. "classifier".
    TEMPLATE_NAME: str = ""
    #: Passed through as BaseAgent's `name` -- also the Prometheus/log label,
    #: so subclasses keep their historical agent name here rather than the
    #: Python class name changing what a metric or log line reports.
    AGENT_NAME: str = ""
    DESCRIPTION: str = ""
    #: Post-generation validators, e.g. ``(assert_no_prompt_leak,)``.
    VALIDATORS: Sequence[Callable[[str], None]] = ()

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Initialize the agent from its class-level template binding.

        Args:
            llm_client: The LLM provider client conforming to BaseLLMClient.
            prompt_manager: Optional prompt manager override (tests only).
        """
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name=self.AGENT_NAME,
            description=self.DESCRIPTION,
            system_prompt=pm.get_template(self.TEMPLATE_NAME),
            validators=list(self.VALIDATORS) or None,
        )
