from typing import Dict, List, Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class MemorySummarizerAgent(BaseAgent):
    """Folds aged-out conversation turns into a short rolling summary."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Initialize the memory summarizer agent.

        Args:
            llm_client: The LLM provider client. The fast tier is enough for
                this -- it is a short consolidation pass, not a generative task.
            prompt_manager: Optional prompt manager override.
        """
        manager = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="MemorySummarizerAgent",
            description="Consolidates aged-out turns into a rolling summary.",
            system_prompt=manager.get_template("memory_summary"),
        )

    async def summarize(
        self, *, existing_summary: str, new_turns: List[Dict[str, str]]
    ) -> str:
        """Fold newly aged-out turns into the existing rolling summary.

        Args:
            existing_summary: The summary carried forward from prior turns.
            new_turns: Turns that just fell outside the verbatim history window.

        Returns:
            The updated summary text.
        """
        turns_text = "\n".join(
            f"{turn.get('role')}: {turn.get('content', '')}" for turn in new_turns
        )
        return await self.run(
            messages="Yukarıdaki bilgiyi kullanarak güncel özeti üret.",
            context={
                "existing_summary": existing_summary or "(Henüz özet yok.)",
                "new_turns": turns_text,
            },
            temperature=0.2,
            max_tokens=300,
        )
