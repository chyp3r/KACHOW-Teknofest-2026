"""Yönlendiricinin kalibre edilmiş füzyon katmanı için uydurulmuş (fitted) katsayılar.

ÜRETİLMİŞ DOSYA -- elle düzenlemeyin. ``evaluation/datasets/intents.jsonl``
kullanılarak ``scripts/fit_router.py`` tarafından üretilmiştir. Altın verinin
(gold set) eğitimle ilgili dilimini, ``app.ai.workflows.router_features``
içindeki özellik kümesini veya ``POLICY_VERSION``'ı değiştirdikten sonra bu
betiği yeniden çalıştırın (ve sonucu commit'leyin).

2026-08-14T21:03:59Z tarihinde 127 eğitim satırına karşı uydurulmuştur
(altın verideki hangi kategorilerin neden hariç tutulduğu için
``scripts/fit_router.py``'nin modül docstring'ine bakın). Uydurma anındaki
5 katlı çapraz doğrulama doğruluğu: 1.0000 -- bu, bir yeniden uydurmayı
karşılaştırmak için bakılacak sayıdır, eğitim doğruluğu değil; bu boyuttaki
bir model birkaç yüz satırda her zaman aşırı öğrenmeye (overfit) meyilli
olacaktır.
"""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.ai.policy import POLICY_VERSION
from app.ai.workflows.router_features import FEATURE_NAMES
from app.ai.workflows.router_fusion import INTENTS

logger = logging.getLogger(__name__)

__all__ = ["RouterWeights", "ROUTER_WEIGHTS"]


@dataclass(frozen=True)
class RouterWeights:
    """Füzyon katmanının uydurulmuş doğrusal katsayıları, niyet başına bir set.

    Attributes:
        version: Bu uydurmanın üretildiği ``POLICY_VERSION``. Aşağıda çalışan
            politikaya karşı kontrol edilir (bir uyarıdır, katı bir hata
            değil -- eskimiş bir anlamsal-prototip dosyasının aksine,
            bu katsayılar reddedilirse yönlendiricinin geri düşebileceği bir
            yedek durum yoktur: füzyon artık isteğe bağlı, eksik bir dosyanın
            basitçe atlanabileceği bir katman değil, karar mekanizmasının
            kendisidir).
        feature_names: Bu katsayıların uydurulduğu tam özellik sırası. İçe
            aktarma (import) anında ``router_features.FEATURE_NAMES``'e karşı
            doğrulanır -- eskimiş bir sürüm damgasının aksine, buradaki
            gerçek bir yapısal uyuşmazlık her skoru sessizce yanlış yapardı,
            bu yüzden bu kontrol gerçekten ölümcüldür (fatal).
        bias: Niyet -> sınıf başına sapma (bias) terimi.
        coefficients: Niyet -> özellik adı -> ağırlık.
    """

    version: str
    feature_names: tuple[str, ...]
    bias: Mapping[str, float]
    coefficients: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if self.feature_names != FEATURE_NAMES:
            raise ValueError(
                "RouterWeights.feature_names does not match the running "
                "router_features.FEATURE_NAMES -- rerun scripts/fit_router.py."
            )
        if set(self.bias) != set(INTENTS) or set(self.coefficients) != set(INTENTS):
            raise ValueError("RouterWeights must cover exactly router_fusion.INTENTS.")
        for intent in INTENTS:
            if set(self.coefficients[intent]) != set(FEATURE_NAMES):
                raise ValueError(
                    f"RouterWeights.coefficients[{intent!r}] does not cover every "
                    "feature in FEATURE_NAMES -- rerun scripts/fit_router.py."
                )


ROUTER_WEIGHTS = RouterWeights(
    version='3.0.0',
    feature_names=(
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
    "prev_revise"
    ),
    bias=MappingProxyType(
        {
        "draft": 0.236768,
        "analyze": -0.013670,
        "assist": 0.094960,
        "revise": -0.318058
        }
    ),
    coefficients=MappingProxyType(
        {
        "draft": MappingProxyType(
        {
            "lex_draft": 1.173179,
            "lex_analyze": -0.398803,
            "lex_assist": -0.194612,
            "lex_revise": -0.247459,
            "lex_margin": -0.192871,
            "sem_draft": 0.040008,
            "sem_analyze": -0.004081,
            "sem_assist": 0.028567,
            "sem_revise": 0.016849,
            "has_document": -0.022023,
            "has_active_draft": -0.099590,
            "is_question": -0.147662,
            "word_count_norm": 0.010870,
            "prev_draft": -0.025933,
            "prev_analyze": -0.008913,
            "prev_revise": -0.008662,
        }
    ),
        "analyze": MappingProxyType(
        {
            "lex_draft": -0.201909,
            "lex_analyze": 1.159511,
            "lex_assist": -0.314900,
            "lex_revise": -0.235052,
            "lex_margin": -0.156536,
            "sem_draft": 0.014254,
            "sem_analyze": 0.015817,
            "sem_assist": -0.000102,
            "sem_revise": 0.002302,
            "has_document": 0.256082,
            "has_active_draft": -0.089091,
            "is_question": -0.025712,
            "word_count_norm": 0.055682,
            "prev_draft": 0.070327,
            "prev_analyze": 0.042009,
            "prev_revise": -0.005211,
        }
    ),
        "assist": MappingProxyType(
        {
            "lex_draft": -0.697781,
            "lex_analyze": -0.514159,
            "lex_assist": 0.931050,
            "lex_revise": -0.460115,
            "lex_margin": 0.237705,
            "sem_draft": -0.024211,
            "sem_analyze": 0.020473,
            "sem_assist": -0.000464,
            "sem_revise": -0.018418,
            "has_document": -0.069610,
            "has_active_draft": -0.099203,
            "is_question": 0.178681,
            "word_count_norm": -0.064116,
            "prev_draft": -0.004791,
            "prev_analyze": -0.017445,
            "prev_revise": 0.022145,
        }
    ),
        "revise": MappingProxyType(
        {
            "lex_draft": -0.273490,
            "lex_analyze": -0.246549,
            "lex_assist": -0.421538,
            "lex_revise": 0.942627,
            "lex_margin": 0.111702,
            "sem_draft": -0.030051,
            "sem_analyze": -0.032209,
            "sem_assist": -0.028002,
            "sem_revise": -0.000734,
            "has_document": -0.164449,
            "has_active_draft": 0.287883,
            "is_question": -0.005307,
            "word_count_norm": -0.002436,
            "prev_draft": -0.039603,
            "prev_analyze": -0.015651,
            "prev_revise": -0.008272,
        }
    )
        }
    ),
)

if ROUTER_WEIGHTS.version != POLICY_VERSION:
    logger.warning(
        "Router fusion weights were fit under policy %s but %s is active -- "
        "scoring with a policy-stale (but structurally valid) model. Rerun "
        "scripts/fit_router.py.",
        ROUTER_WEIGHTS.version,
        POLICY_VERSION,
    )
