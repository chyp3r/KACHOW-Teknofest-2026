from app.ai.agents.template_agent import TemplateAgent


class ConflictAuditorAgent(TemplateAgent):
    """Zaten uygulanmış bir revizyonu mevzuat/kaynak ile çelişki açısından denetler.

    Yeniden yazım taslağa çoktan birleştirildikten sonra hızlı katmanda çalışır
    -- kullanıcının talimatını uygulamadan önce veya onun yerine asla çalışmaz
    (bkz. app.ai.revision.conflict modülünün docstring'i). Tek görevi, bir
    insanın görmesi için çelişkileri raporlamaktır; incelediği düzenlemeyi asla
    geri almaz veya yumuşatmaz.
    """

    TEMPLATE_NAME = "conflict_auditor"
    AGENT_NAME = "ConflictAuditorAgent"
    DESCRIPTION = (
        "Zaten uygulanmış bir kullanıcı revizyon talimatı ile getirilen "
        "mevzuat/kaynak belge arasındaki çelişkileri raporlar -- incelediği "
        "düzenlemeyi asla geri almaz veya yumuşatmaz."
    )
