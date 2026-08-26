from typing import Optional

from app.ai.agents.base import BaseAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class ReviserAgent(BaseAgent):
    """Daha önce üretilmiş bir taslağa numaralandırılmış bir kusur listesi uygular.

    WriterAgent'tan ayrı bir sınıf, böylece "yalnızca listelenmiş olanı düzelt,
    hiçbir şey uydurma" kısıtı, modelin önceliğini düşürebileceği bir
    kullanıcı-turu önerisi yerine sistem seviyesinde bir prompt olur.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name="ReviserAgent",
            description="Bir taslağı sıfırdan yeniden üretmeden listelenmiş kusurlarını onarır.",
            system_prompt=pm.get_template("reviser"),
            validators=[assert_no_prompt_leak],
        )
