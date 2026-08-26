"""Reasoning-level (akıl yürütme seviyesi) ön ayarları: kullanıcının
seçebileceği bir hız-kalite ödünleşimi.

Üç seviye, hepsi bu codebase'de zaten var olan iki LLM katmanı ve
düğmelerden inşa edilmiş (``get_llm_client``/``get_fast_llm_client``,
Ollama'nın ``reasoning`` kwarg'ı, taslak reflexion döngüsünün deneme sınırı
ve judge kapısı) -- hiçbir seviye üçüncü bir yerleşik model eklemez.
``deep``, *var olan* kalite katmanı modeli üzerinde daha fazla çıkarım
zamanı hesaplaması harcayarak (thinking mode, ek reflexion geçişleri,
zorunlu bir judge geçişi) saat süresini kaliteyle takas eder; ``fast``,
serbest metin üretimini zaten ısınmış hızlı katman modeli üzerinden
yönlendirerek kaliteyi hızla takas eder. ``balanced``, bugünün sabit
kodlanmış draft_graph.py varsayılanlarını tam olarak yeniden üretir, bu
yüzden sıfır davranışsal değişiklik taşır.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from app.core.enums.reasoning_level import ReasoningLevel

#: Bugünün sabit kodlanmış draft_graph.py varsayılanları, tek gerçek kaynağı
#: olarak burada tutulur; böylece BALANCED'ın reasoning-level öncesi
#: davranışla özdeş olduğu kanıtlanabilir.
_BALANCED_DRAFT_MAX_TOKENS = 2048
_BALANCED_MAX_DRAFT_ATTEMPTS = 2


@dataclass(frozen=True)
class ReasoningLevelPreset:
    """Tek bir reasoning seviyesi için çözümlenmiş düğmeler."""

    level: ReasoningLevel
    label_tr: str
    model_tier: Literal["fast", "quality"]
    reasoning: bool
    max_draft_attempts: int
    #: None, "settings.DRAFT_JUDGE_ENABLED'a uy" anlamına gelir; True/False onu zorlar.
    judge_enabled: Optional[bool]
    draft_max_tokens: int
    timeout_multiplier: float


_PRESETS: dict[ReasoningLevel, ReasoningLevelPreset] = {
    ReasoningLevel.FAST: ReasoningLevelPreset(
        level=ReasoningLevel.FAST,
        label_tr="Hızlı",
        model_tier="fast",
        reasoning=False,
        max_draft_attempts=1,
        judge_enabled=False,
        draft_max_tokens=_BALANCED_DRAFT_MAX_TOKENS,
        timeout_multiplier=0.6,
    ),
    ReasoningLevel.BALANCED: ReasoningLevelPreset(
        level=ReasoningLevel.BALANCED,
        label_tr="Dengeli",
        model_tier="quality",
        reasoning=False,
        max_draft_attempts=_BALANCED_MAX_DRAFT_ATTEMPTS,
        judge_enabled=None,
        draft_max_tokens=_BALANCED_DRAFT_MAX_TOKENS,
        timeout_multiplier=1.0,
    ),
    ReasoningLevel.DEEP: ReasoningLevelPreset(
        level=ReasoningLevel.DEEP,
        label_tr="Derin",
        model_tier="quality",
        reasoning=True,
        max_draft_attempts=3,
        judge_enabled=True,
        # Thinking-mode'un <think>...</think> token'ları num_predict'i son
        # cevapla paylaşır; reasoning=True olduğunda balanced bütçe çok dar kalır.
        draft_max_tokens=3072,
        timeout_multiplier=1.8,
    ),
}


def get_reasoning_level_preset(level: "ReasoningLevel | str | None") -> ReasoningLevelPreset:
    """Bir reasoning seviyesini kendi ön ayarına çözümler, güvenle BALANCED'a varsayılan olarak döner.

    ``level``, checkpoint'lenmiş LangGraph durumundan veya bir istemci
    isteğinden gelebilir, bu yüzden bilinmeyen, eksik veya hatalı
    biçimlendirilmiş bir değer asla hata fırlatmamalıdır -- bunun yerine
    sessizce bugünün varsayılan davranışına düşer.
    """
    if level is None:
        return _PRESETS[ReasoningLevel.BALANCED]
    try:
        resolved = ReasoningLevel(level)
    except ValueError:
        return _PRESETS[ReasoningLevel.BALANCED]
    return _PRESETS[resolved]


__all__ = ["ReasoningLevelPreset", "get_reasoning_level_preset"]
