"""Router'ın özellik vektörünü niyet başına tek bir kalibre olasılığa birleştirir.

Bir softmax'tan geçen dört bire-karşı-hepsi doğrusal skordan oluşan
multinom bir lojistik model; sade Python aritmetiği olarak bir avuç float
üzerinde değerlendirilir -- numpy yok, çıkarım çerçevesi yok. Katsayılar,
``evaluation/datasets/intents.jsonl``'a karşı ``scripts/fit_router.py``
tarafından çevrimdışı olarak fit edilen, dondurulmuş bir dataclass olarak
``app.ai.policy.router_weights`` içinde yaşar; ``scripts/build_prototypes.py``'nin
vektörleriyle aynı "bir kere fit et, dondur, sayıları içeri al" şeklindedir.

Neden elle seçilmiş başka bir ağırlık tablosu yerine öğrenilmiş bir
kombinasyon: bunun yerini aldığı tablo (``intent_rules.py``'daki
``WEIGHT_EXPLICIT``/``WEIGHT_HINT``/...) zaten manuel olarak ayarlanmış
doğrusal bir kombinasyon*dur*, sadece yazılırken akla gelen örneklere göre
göz kararı ayarlanmıştır. K2 regresyonu (açık bir emir kipinin yapısal bir
ipucuna 0.2'lik bir farkla kaybetmesi) tam olarak elle ayarlamanın hata
modudur: ağırlıklar hiçbir zaman bileşik ve yapısal kuralların aynı
mesajda *birlikte* tetiklenmesine karşı kontrol edilmedi. Tüm altın seti bir
kerede, her katsayıyı cezalandıran aynı düzenlileştirme terimiyle fit edilen
bir model bu kör noktaya sahip değildir -- ya açık bir isabetin yapısal bir
ipucuna baskın gelmesi gerektiğini öğrenir, ya da altın set aslında bu
iddiayı desteklemez; her iki durumda da cevap tahmin edilmek yerine
ölçülmüştür.
"""

import math
from typing import TYPE_CHECKING

from app.ai.workflows.intent_rules import Intent
from app.ai.workflows.router_features import FEATURE_NAMES

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from app.ai.policy.router_weights import RouterWeights

__all__ = ["INTENTS", "predict_proba", "softmax"]

#: Sabit sınıf sırası. `router_features._INTENTS` ve
#: `RouterWeights.coefficients`'in anahtarlarıyla eşleşir; bağımsız tutulur
#: (`router_features`'tan import edilmez) böylece bu modülün genel sözleşmesi
#: gizlice o modülün özel sıralamasını kapsayacak şekilde genişlemez.
INTENTS: tuple[Intent, ...] = ("draft", "analyze", "assist", "revise")


def softmax(logits: dict[str, float]) -> dict[str, float]:
    """Sınıf başına logit'leri bir olasılık dağılımına dönüştürür.

    Args:
        logits: Sınıf -> normalize edilmemiş skor.

    Returns:
        Sınıf -> olasılık, toplamı 1.0.
    """
    if not logits:
        return {}
    # Üstel alma öncesi maksimumu çıkar -- klasik taşma koruması; softmax
    # kaydırmaya karşı değişmez olduğu için bu sayısal değerler dışında
    # hiçbir şeyi değiştirmez.
    ceiling = max(logits.values())
    exponentials = {label: math.exp(value - ceiling) for label, value in logits.items()}
    total = sum(exponentials.values())
    return {label: value / total for label, value in exponentials.items()}


def predict_proba(
    features: dict[str, float], weights: "RouterWeights"
) -> dict[str, float]:
    """Bir özellik vektörünü niyet başına kalibre bir olasılığa dönüştürür.

    Args:
        features: ``FEATURE_NAMES`` ile anahtarlanmış
            ``router_features.extract_features`` çıktısı.
        weights: Fit edilmiş katsayılar.

    Returns:
        Niyet -> [0, 1] aralığında olasılık, toplamı 1.0.
    """
    logits: dict[str, float] = {}
    for intent in INTENTS:
        coefficients = weights.coefficients[intent]
        logit = weights.bias[intent]
        for name in FEATURE_NAMES:
            logit += coefficients.get(name, 0.0) * features.get(name, 0.0)
        logits[intent] = logit
    return softmax(logits)
