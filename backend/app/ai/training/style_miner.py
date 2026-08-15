"""Turns a company's compiled preference pairs into a `CompanyAdapter`'s
`style_rules`/`avoided_patterns` -- Faz C3 (#187), Aşama 2 of the plan.

One training run makes **one** LLM call, never one per sample or per
message (see the plan's own A6 note on why a third "nano" model layer
was rejected and `fast_llm_client` load was measured instead) -- the
deterministic diff signals below do the heavy lifting; the LLM call only
turns already-computed statistics plus a small capped sample of the actual
texts into Turkish prose rules.

No `app.domains` import here either, same rule as `dataset.py`: the caller
(`app.domains.training.service`) resolves `pairs` and hands them in.
"""

from dataclasses import dataclass
from statistics import mean
from typing import List, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.training.dataset import PreferencePair

#: Below this many compiled pairs, mining is skipped rather than run on too
#: little signal to be more than noise -- `app.domains.training.service`
#: checks this before calling `mine_style` and records the run as
#: `"skipped"`, not `"failed"`.
MIN_FEEDBACK_SAMPLES = 50

#: Style rules / avoided patterns lists are capped the same way
#: `CompanyAdapterUpdate` caps hand-authored ones (see `company_schema.py`).
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
    """Cheap, LLM-free diff stats between liked and disliked text -- fed
    into the single LLM call's prompt as grounding, not a replacement for
    it (average length alone cannot express "hitap biçimi" or "kapanış
    kalıbı")."""
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
    """Returns `None` when there are fewer than `MIN_FEEDBACK_SAMPLES`
    pairs -- the caller treats that as "skip," not an error."""
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
