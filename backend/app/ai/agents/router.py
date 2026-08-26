from app.ai.agents.template_agent import TemplateAgent


class RouterAgent(TemplateAgent):
    """Verilen bir isteği ele almak için en uygun ajan, araç veya iş akışı yolunu belirlemekten sorumlu Yönlendirici (Router) Ajan."""

    TEMPLATE_NAME = "router"
    AGENT_NAME = "RouterAgent"
    DESCRIPTION = "Gelen istekleri analiz eder ve en uygun uzmanlaşmış ajana veya iş akışına yönlendirir."
