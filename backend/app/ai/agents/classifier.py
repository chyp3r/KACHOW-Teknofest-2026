from app.ai.agents.template_agent import TemplateAgent
from app.ai.guardrails.injection import assert_no_prompt_leak


class ClassifierAgent(TemplateAgent):
    """Metinleri sınıflandırmaktan, istekleri kategorize etmekten ve duygu analizi yapmaktan sorumlu Sınıflandırıcı Ajan."""

    TEMPLATE_NAME = "classifier"
    AGENT_NAME = "ClassifierAgent"
    DESCRIPTION = "Metni önceden tanımlı kategorilere/etiketlere ayırır ve duygu analizi yapar."
    VALIDATORS = (assert_no_prompt_leak,)
