from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient

class ChatAgent(BaseAgent):
    """An agent that just talks to the user for plain conversations."""
    def __init__(self, llm_client: BaseLLMClient):
        from app.ai.prompts.manager import PromptManager
        pm = PromptManager()
        sys_prompt = pm.get_template("chat")
        super().__init__(
            llm_client=llm_client,
            name="chat",
            description="An agent that talks to the user.",
            system_prompt=sys_prompt
        )
