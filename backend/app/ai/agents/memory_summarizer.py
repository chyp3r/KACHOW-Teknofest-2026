from typing import Dict, List, Optional

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class MemorySummarizerAgent(BaseAgent):
    """Süresi dolmuş konuşma turlarını kısa, kayan bir özete katlar."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Hafıza özetleyici ajanını başlatır.

        Args:
            llm_client: LLM sağlayıcı istemcisi. Bunun için hızlı katman
                yeterlidir -- bu üretken bir görev değil, kısa bir birleştirme
                geçişidir.
            prompt_manager: Opsiyonel prompt yöneticisi override'ı.
        """
        manager = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="MemorySummarizerAgent",
            description="Süresi dolmuş turları kayan bir özette birleştirir.",
            system_prompt=manager.get_template("memory_summary"),
        )

    async def summarize(
        self, *, existing_summary: str, new_turns: List[Dict[str, str]]
    ) -> str:
        """Yeni süresi dolmuş turları mevcut kayan özete katlar.

        Args:
            existing_summary: Önceki turlardan taşınan özet.
            new_turns: Az önce birebir geçmiş penceresinin dışına düşen turlar.

        Returns:
            Güncellenmiş özet metni.
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
