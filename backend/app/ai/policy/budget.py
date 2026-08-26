"""Devam eden çalışmanın akıl yürütme seviyesi için bir düğümün zaman bütçesini çözer.

``reasoning_levels.py`` özelliğin eklendiği andan beri bir ``timeout_multiplier``
taşıyor (0.6 hızlı, 1.0 dengeli, 1.8 derin), ama bu çarpan yalnızca *servis*
katmanının dış zaman aşımına ulaşabiliyordu. Düğüm bütçeleri sabit kaldığı için
``deep`` bir çalışmaya toplam duvar saatinin 1.8 katı veriliyordu ama her bir
düğüm kendi dengeli tavanını koruyordu -- ekstra bütçe, ekstra işin gerçekten
yapıldığı yerde harcanamıyordu.

Çözümleme, grafik derlemesi başına değil çağrı başına yapılır. ``@node_timeout``
eskiden bir float alıyordu; bu da bütçenin grafik derlenirken sabitlendiği
anlamına geliyordu. Bir grafik süreç başına yalnızca bir kez derlendiğinden,
istek başına bir değer ona asla ulaşamazdı. Bir düğüm *adı* alıp çağrı anında
çözümlemek, çarpanı kullanılabilir kılan şeydir.
"""

from app.ai.policy import get_policy
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.core.enums.reasoning_level import ReasoningLevel

__all__ = ["node_budget"]


def node_budget(node: str, level: "ReasoningLevel | str | None" = None) -> float:
    """Bir akıl yürütme seviyesinde tek bir düğüm için zaman aşımı bütçesini çözer.

    Args:
        node: Düğümün adı, ``BudgetPolicy.node_seconds`` içindeki anahtarıyla aynı.
        level: Çalışmanın akıl yürütme seviyesi. Bilinmeyen, eksik veya bozuk
            değerler dengeli olarak çözümlenir -- bu değer, kontrol noktası
            alınmış grafik durumundan okunur ve daha eski bir sürüm tarafından
            yazılmış bir değerde asla hata fırlatmamalıdır.

    Returns:
        Seviyenin çarpanıyla ölçeklenmiş ve tüm iş akışının tavanına
        sınırlandırılmış saniye cinsinden bütçe. Yapılandırılmış bütçesi
        olmayan bir düğüm, kazara sıfır saniyelik bir zaman aşımı yerine
        etkisiz (no-op) bir zaman aşımı olan tavana geri döner.
    """
    policy = get_policy().budget
    base = policy.node_seconds.get(node)
    if base is None:
        return policy.workflow_ceiling_seconds

    scaled = base * get_reasoning_level_preset(level).timeout_multiplier
    return min(scaled, policy.workflow_ceiling_seconds)
