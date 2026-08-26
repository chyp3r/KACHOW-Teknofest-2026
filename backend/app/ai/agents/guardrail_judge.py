from app.ai.agents.template_agent import TemplateAgent


class GuardrailJudgeAgent(TemplateAgent):
    """Deterministik desenlerin göremediği anlam düzeyindeki hassasiyeti/sızıntıyı değerlendirir.

    Hızlı katmanda, ``JudgeAgent`` ile aynı biçimde çalışır: küçük,
    yapılandırılmış bir karar üretir, asla değerlendirilen içeriğin kendisini
    değil; bu yüzden maliyeti etiket boyutunda bir üretimdir. Çağıran prompt
    tarafından seçilen iki görev için kullanılır (girdi belgesi hassasiyeti,
    çıktı yanıtı sızıntısı) -- bkz. ``app.ai.guardrails.llm_nuance``.
    """

    TEMPLATE_NAME = "guardrail_judge"
    AGENT_NAME = "GuardrailJudgeAgent"
    DESCRIPTION = (
        "Bir belgenin veya yanıtın desen değil anlam düzeyinde hassas/sızdırıcı "
        "olup olmadığını değerlendirir -- regex'in göremeyeceği inceliği yakalar."
    )
