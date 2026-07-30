from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient

class ChatAgent(BaseAgent):
    """An agent that just talks to the user for plain conversations."""
    def __init__(self, llm_client: BaseLLMClient):
        super().__init__(
            llm_client=llm_client,
            system_prompt_template="chat.md"
        )
