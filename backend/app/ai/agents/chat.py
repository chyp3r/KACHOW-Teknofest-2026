from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class ChatAgent(BaseAgent):
    """An agent that just talks to the user for plain conversations."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: "PromptManager | None" = None,
    ):
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="chat",
            description="An agent that talks to the user.",
            system_prompt=pm.get_template("chat"),
        )
