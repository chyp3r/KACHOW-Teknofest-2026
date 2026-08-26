"""Bir kurumun derlenmiş tercih çiftlerini bir `CompanyAdapter`'ın
`style_rules`/`avoided_patterns`'ına dönüştürür -- Faz C3 (#187), planın
Aşama 2'si.

Bir eğitim koşusu **tek** bir LLM çağrısı yapar, örnek başına veya mesaj
başına asla değil (üçüncü bir "nano" model katmanının neden reddedildiği
ve bunun yerine `fast_llm_client` yükünün ölçüldüğü için planın kendi A6
notuna bakın) -- ağır işi aşağıdaki deterministik diff sinyalleri yapar;
LLM çağrısı yalnızca zaten hesaplanmış istatistikleri, gerçek metinlerin
küçük ve sınırlı bir örneğiyle birlikte Türkçe düzyazı kurallara çevirir.

`dataset.py` ile aynı kural gereği burada da `app.domains` import'u yok:
çağıran (`app.domains.training.service`) `pairs`'i çözümler ve buraya
aktarır.
"""

from dataclasses import dataclass
from statistics import mean
from typing import List, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.training.dataset import PreferencePair

#: Bu sayının altındaki derlenmiş çiftlerde, gürültüden fazlası olamayacak
#: kadar az sinyal üzerinde çalıştırmak yerine mining atlanır --
#: `app.domains.training.service`, `mine_style`'ı çağırmadan önce bunu
#: kontrol eder ve koşuyu `"failed"` değil `"skipped"` olarak kaydeder.
MIN_FEEDBACK_SAMPLES = 50

#: Style rules / avoided patterns listeleri, `CompanyAdapterUpdate`'in
#: elle yazılanları sınırladığı aynı şekilde sınırlanır (bkz. `company_schema.py`).
_MAX_RULES = 10
_MAX_EXAMPLES_PER_SIDE = 6
_MAX_EXAMPLE_CHARS = 600


@dataclass(frozen=True)
class MinedStyle:
    style_rules: tuple
    avoided_patterns: tuple
    sample_count: int


class _StyleMiningResult(BaseModel):
    style_rules: List[str] = Field(default_factory=list, max_length=_MAX_RULES)
    avoided_patterns: List[str] = Field(default_factory=list, max_length=_MAX_RULES)


def _deterministic_signals(pairs: List[PreferencePair]) -> dict:
    """Beğenilen ve beğenilmeyen metin arasında ucuz, LLM'siz diff
    istatistikleri -- tek LLM çağrısının promptuna dayanak (grounding)
    olarak beslenir, onun yerine geçmez (yalnızca ortalama uzunluk "hitap
    biçimi" veya "kapanış kalıbı"nı ifade edemez)."""
    liked = [p.chosen for p in pairs if p.chosen]
    disliked = [p.rejected for p in pairs if p.rejected]
    signals = {"liked_count": len(liked), "disliked_count": len(disliked)}
    if liked:
        signals["avg_liked_length"] = round(mean(len(text) for text in liked))
    if disliked:
        signals["avg_disliked_length"] = round(mean(len(text) for text in disliked))
    return signals


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_EXAMPLE_CHARS else text[:_MAX_EXAMPLE_CHARS] + "…"


def _build_prompt(signals: dict, pairs: List[PreferencePair]) -> List[dict]:
    liked_examples = [_truncate(p.chosen) for p in pairs if p.chosen][:_MAX_EXAMPLES_PER_SIDE]
    disliked_examples = [_truncate(p.rejected) for p in pairs if p.rejected][:_MAX_EXAMPLES_PER_SIDE]

    signal_lines = "\n".join(f"- {key}: {value}" for key, value in signals.items())
    liked_block = "\n\n".join(f"[Beğenilen #{i + 1}]\n{text}" for i, text in enumerate(liked_examples))
    disliked_block = "\n\n".join(
        f"[Beğenilmeyen #{i + 1}]\n{text}" for i, text in enumerate(disliked_examples)
    )

    user_content = (
        "Aşağıda bir kurumun resmî yazışma taslakları için kullanıcılardan toplanan "
        "beğeni/beğenmeme sinyalleri var. Beğenilen örneklerin ortak üslup "
        "özelliklerini ve beğenilmeyenlerden kaçınılması gereken kalıpları çıkar.\n\n"
        f"İstatistikler:\n{signal_lines}\n\n"
        f"{liked_block}\n\n{disliked_block}\n\n"
        "Yalnızca ÜSLUP, TON ve BİÇİM hakkında kurallar üret -- asla olgu, kurum adı "
        "veya belge içeriği tekrar etme (bu kurallar farklı belgelere uygulanacak). "
        "En fazla 10 style_rules ve 10 avoided_patterns maddesi, her biri kısa ve "
        "Türkçe bir talimat cümlesi olarak."
    )
    return [
        {
            "role": "system",
            "content": (
                "Sen resmî yazışma üslubu analiz eden bir asistansın. Yalnızca "
                "biçimsel/üslupsal örüntüleri çıkarırsın, belge içeriği veya "
                "kurum/isim bilgisi asla üretmezsin."
            ),
        },
        {"role": "user", "content": user_content},
    ]


async def mine_style(
    llm_client: BaseLLMClient, pairs: List[PreferencePair]
) -> Optional[MinedStyle]:
    """`MIN_FEEDBACK_SAMPLES`'dan az çift olduğunda `None` döner -- çağıran
    bunu bir hata değil, "atla" olarak ele alır."""
    if len(pairs) < MIN_FEEDBACK_SAMPLES:
        return None

    signals = _deterministic_signals(pairs)
    messages = _build_prompt(signals, pairs)
    result = await llm_client.generate_structured(
        messages=messages, response_model=_StyleMiningResult, temperature=0.0
    )
    return MinedStyle(
        style_rules=tuple(result.style_rules[:_MAX_RULES]),
        avoided_patterns=tuple(result.avoided_patterns[:_MAX_RULES]),
        sample_count=len(pairs),
    )
