"""Bir mesajı ve bağlamını füzyon katmanının özellik vektörüne dönüştürür.

Eski merdiven, ilk cevap veren basamağın tek başına karar vermesine izin
veriyordu: sözcüksel katmanın marjı her şeyi kapı gibi kontrol ediyordu, ve
anlamsal basamak yalnızca sözcüksel katman zaten çekimser kaldığında devreye
giriyordu. Bir açık emir kipi ile bir yapısal ipucu taşıyan bir mesajın (bkz.
K2 regresyonu -- "Cevap yaz." `assist.short_message`'tan gelen `assist=2.0`
ipucuna karşı `draft=3.0` puanı alıyor, marj ``1.0 < 1.2``) çözülmek yerine
bir açıklayıcı soruya düşmesinin nedeni budur: marj testi açık bir emir
kipini zayıf bir yapısal ipucundan ayırt edemez, çünkü ikisi de zaten aynı
niyet başına toplamın içine katlanmıştır.

Bu modül, her sinyal kaynağını önceden toplamak yerine ayrı tutar; böylece
``router_fusion``'ın kalibre ağırlıkları her birinin diğerlerine göre ne
kadar değerli olduğunu öğrenebilir -- açık bir sözcüksel isabet, elle seçilen
``WEIGHT_EXPLICIT``/``WEIGHT_HINT`` sabitlerinin tesadüfen ürettiği bir
miktarla değil, öğrenilmiş bir miktarla yapısal bir ipucundan ağır basmalıdır.
"""

from dataclasses import dataclass
from typing import Optional

from app.ai.workflows.intent_rules import Intent
from app.ai.workflows.intent_scorer import IntentScores, looks_like_question, normalize

__all__ = ["FEATURE_NAMES", "extract_features"]

#: Füzyon katmanının arasında karar verdiği dört niyet. `clarify` bunlardan
#: biri değildir -- bu, hiçbir niyetin füzyonlanmış olasılığı düşük eşiği
#: geçemediğinde karar *politikasının* düştüğü bir yedektir, modelin
#: tahmin ettiği bir sınıf değildir.
_INTENTS: tuple[Intent, ...] = ("draft", "analyze", "assist", "revise")

#: Sabit özellik sırası. `router_fusion.predict_proba` ve
#: `scripts/fit_router.py` ikisi de bu tuple üzerinde döner, bu yüzden bir
#: özellik ikisine de dokunmadan buraya eklenebilir -- ağırlık dataclass'ının
#: sadece eşleşen bir girişe ihtiyacı vardır, bu da
#: `RouterWeights.__post_init__` tarafından kontrol edilir (bkz.
#: `app.ai.policy.router_weights`).
FEATURE_NAMES: tuple[str, ...] = (
    "lex_draft",
    "lex_analyze",
    "lex_assist",
    "lex_revise",
    "lex_margin",
    "sem_draft",
    "sem_analyze",
    "sem_assist",
    "sem_revise",
    "has_document",
    "has_active_draft",
    "is_question",
    "word_count_norm",
    "prev_draft",
    "prev_analyze",
    "prev_revise",
)


@dataclass(frozen=True)
class RouterSignals:
    """`extract_features`'ın bir özellik vektörüne dönüştürdüğü ham kanıt.

    Beş ayrı bağımsız değişken geçmek yerine adlandırılmış, incelenebilir
    bir demet olarak tutulur; böylece bunu aşamalı olarak oluşturan bir
    çağıranın -- sözcüksel her zaman, anlamsal yalnızca eşleştirici
    mevcutken -- teslim edecek tek bir nesnesi olur.
    """

    lexical: IntentScores
    semantic: Optional[dict[str, float]]
    has_document: bool
    has_active_draft: bool
    previous_intent: Optional[str]


def extract_features(message: str, signals: RouterSignals) -> dict[str, float]:
    """Bir mesaj için füzyon katmanının özellik vektörünü oluşturur.

    Args:
        message: Kullanıcının ham mesajı (kelime sayısı ve soru-şekli
            sezgisel yöntemi için kullanılır; eşleştirmenin kendisi zaten
            ``signals.lexical``'ı üretmek için yapılmıştı).
        signals: Bu tur için zaten toplanmış her kanıt parçası.

    Returns:
        Tam olarak ``FEATURE_NAMES`` ile anahtarlanmış özellik adı -> değer.
    """
    normalized = normalize(message)
    words = normalized.split()

    features = {name: 0.0 for name in FEATURE_NAMES}

    for intent in _INTENTS:
        features[f"lex_{intent}"] = signals.lexical.scores.get(intent, 0.0)
    features["lex_margin"] = signals.lexical.margin

    if signals.semantic:
        for intent in _INTENTS:
            features[f"sem_{intent}"] = signals.semantic.get(intent, 0.0)

    features["has_document"] = 1.0 if signals.has_document else 0.0
    features["has_active_draft"] = 1.0 if signals.has_active_draft else 0.0
    features["is_question"] = 1.0 if looks_like_question(message, normalized) else 0.0
    # Ham değil sınırlandırılmış: 4 kelimelik bir mesaj ile 40 kelimelik bir
    # mesaj, doğrusal bir modelin 0/1 bayraklarıyla birlikte ağırlıklandırdığı
    # bir özellikte on kat farklı olmamalıdır.
    features["word_count_norm"] = min(len(words), 10) / 10.0

    if signals.previous_intent == "draft":
        features["prev_draft"] = 1.0
    elif signals.previous_intent == "analyze":
        features["prev_analyze"] = 1.0
    elif signals.previous_intent == "revise":
        features["prev_revise"] = 1.0

    return features
