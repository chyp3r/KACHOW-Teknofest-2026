from app.ai.agents.template_agent import TemplateAgent


class JudgeAgent(TemplateAgent):
    """Bir taslağı, deterministik doğrulayıcının kontrol edemeyeceği ölçütlere göre değerlendirir.

    Hızlı katmanda çalışır: küçük, yapılandırılmış bir karar üretir, asla
    taslak metnin kendisini değil; bu yüzden maliyeti ikinci bir tam taslak
    değil, etiket boyutunda bir üretimdir.
    """

    TEMPLATE_NAME = "judge"
    AGENT_NAME = "JudgeAgent"
    DESCRIPTION = (
        "Bir taslağın isteğe uygunluğunu, üslubunu, kapanış yönünü ve muhatap "
        "tutarlılığını değerlendirir -- kalitenin regex ile görülemeyen kısımları."
    )
