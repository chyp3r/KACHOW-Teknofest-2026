from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class WriterAgent(BaseAgent):
    """Yüksek kaliteli raporlar, özetler, makaleler ve metin yanıtları üretmekten sorumlu Yazar Ajanı.

    Buradaki ``validators`` yalnızca gelecekteki bir ``.run()``/``.run_structured()``
    çağrısını korur -- ``draft_graph.writer_node`` ``.stream()`` kullanır, bu da
    yayınlamadan önce doğrulama yapamaz; bu yüzden biriken taslak metin
    üzerindeki gerçek koruma o node içinde bulunur.
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
            description="Metin, rapor, taslak, özet ve yapılandırılmış yazılı yanıtlar üretir.",
            system_prompt=system_prompt,
            validators=[assert_no_prompt_leak],
        )
