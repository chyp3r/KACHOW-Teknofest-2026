from typing import Callable, Optional, Sequence

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.prompts.manager import PromptManager, get_prompt_manager


class TemplateAgent(BaseAgent):
    """Adı verilmiş bir prompt şablonundan başka bir şey olmayan bir ajan.

    ``ClassifierAgent``, ``ComplianceAgent``, ``RouterAgent`` ve
    ``JudgeAgent`` her biri kendi başka davranışları olmadan aynı
    ``__init__``'i (isimle şablon yükle, name/description/validators'ı
    ``BaseAgent``'a ilet) yeniden uyguluyordu. Artık bunu alt sınıflandırıyor
    ve bunun yerine aşağıdaki üç sınıf özniteliğini ayarlıyorlar. Sınıf adı,
    modül yolu ve constructor imzası değişmedi, bu yüzden mevcut her çağrı
    noktası ve test çalışmaya devam ediyor -- birkaç test noktalı yol ile
    patch uyguluyor (örn. ``app.ai.agents.classifier.ClassifierAgent.
    run_structured``), ki bu dördünü de değiştiren tek bir paylaşılan sınıf
    bunu bozardı.
    """

    #: prompts/templates/ içindeki şablon adı, örn. "classifier".
    TEMPLATE_NAME: str = ""
    #: BaseAgent'ın `name`i olarak iletilir -- aynı zamanda Prometheus/log
    #: etiketi, bu yüzden alt sınıflar tarihsel ajan adlarını burada
    #: tutuyorlar; Python sınıf adının bir metrik veya log satırının
    #: raporladığı şeyi değiştirmesi yerine.
    AGENT_NAME: str = ""
    DESCRIPTION: str = ""
    #: Üretim sonrası doğrulayıcılar, örn. ``(assert_no_prompt_leak,)``.
    VALIDATORS: Sequence[Callable[[str], None]] = ()

    def __init__(
        self,
        llm_client: BaseLLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        """Ajanı, sınıf seviyesindeki şablon bağlamasından başlatır.

        Args:
            llm_client: BaseLLMClient'a uyan LLM sağlayıcı istemcisi.
            prompt_manager: Opsiyonel prompt yöneticisi override'ı (yalnızca testler için).
        """
        pm = prompt_manager or get_prompt_manager()
        super().__init__(
            llm_client=llm_client,
            name=self.AGENT_NAME,
            description=self.DESCRIPTION,
            system_prompt=pm.get_template(self.TEMPLATE_NAME),
            validators=list(self.VALIDATORS) or None,
        )
