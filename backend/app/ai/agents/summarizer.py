from app.ai.agents.template_agent import TemplateAgent


class SummarizerAgent(TemplateAgent):
    """Bir belge veya parçanın ayrıntılı, sınırsız uzunlukta Türkçe özetini üretir.

    ``ClassifierAgent``'ı yeniden kullanmak yerine bilinçli olarak kendi
    ajanı: ``classifier.md`` (ClassifierAgent'ın kendi şablonu) sistem
    prompt'unda "Özet en fazla 3 cümle olsun" ifadesini sabit koder --
    ``analyze_node``'un birleştirilmiş şema Field açıklamasının (bkz.
    ``document_analysis_graph.SummaryOutput``) yanında üç cümlelik sınırın
    ikinci, bağımsız kaynağı. Burada ``classifier_agent``'ı yeniden kullanmak,
    bu kısıtı şemadan kaldırdıktan sonra bile sistem prompt'u aracılığıyla
    yürürlükte tutardı; bu yüzden bunun asla bir uzunluk sınırı belirtmeyen
    kendi şablonuna ihtiyacı var.
    """

    TEMPLATE_NAME = "summarizer"
    AGENT_NAME = "SummarizerAgent"
    DESCRIPTION = "Resmi bir belgenin ayrıntılı, kısaltılmamış Türkçe özetini üretir."
