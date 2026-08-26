"""Tercih-çifti (preference-pair) derlemesi -- Faz C3 (#187).

Yalnızca saf fonksiyonlar: zaten çözümlenmiş feedback satırlarını
`PreferencePair`lara dönüştürür. `app.ai.adapters.company_adapter`'ın
belgelediği kuralla aynı şekilde bilerek sıfır `app.domains` import'u
içerir -- asıl `feedback`/`drafts` okumaları `app.domains.training.service`
içinde yaşar, o da bu modülü ORM satırlarıyla değil düz veriyle çağırır.

Bugün yalnızca `explicit_feedback` derleniyor (değerlendirilen metni bir
`DraftModel.content`'e geri çözümlenebilen bir 👍/👎 oyu). Planın "örtük
sinyaller"i (implicit HITL approve/reject/revise izi) burada kasıtlı olarak
henüz derlenmiyor -- nedeni için `TrainingSampleModel`'in docstring'ine
bakın: bugün `drafts.status` bir workflow sonucunu kaydeder, kullanıcının
kabul/red kararını değil, ve yanlış alandan bir tercih etiketi uydurmak bir
stil adaptörünün eğitildiği verinin ta kendisini yanlış etiketlemek olur.
`app.domains.feedback.model.feedback_model.FeedbackModel` docstring'inin
tam olarak aynı kuralını burada da tekrarlıyoruz: "modelin kendi tahmini
asla bir etiket olarak kullanılmaz" -- belirsiz bir status da öyle.
"""

import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class FeedbackRecord:
    """Değerlendirilen metni zaten çözümlenmiş tek bir `feedback` oyu
    (`draft_id` -> `DraftModel.content` üzerinden; bir oyun geri işaret
    edebileceği tek kalıcı metin deposu -- oyun ham metni neden hiçbir
    zaman kendisi taşımadığı için `FeedbackModel`'in docstring'ine bakın).

    Metni çözümlenemeyen bir oy (ne `draft_id` var ne de draft satırı
    mevcut) çağıran tarafından hiçbir zaman bir `FeedbackRecord`'a
    dönüştürülmez -- bu modülün metinsiz bir çift türetebileceği bir şey
    yoktur.
    """

    feedback_id: str
    signal: str  # "like" | "dislike"
    content: str
    draft_id: Optional[str] = None
    correspondence_type: Optional[str] = None
    confidence_score: Optional[float] = None


@dataclass(frozen=True)
class PreferencePair:
    """`app.domains.training.service`'in `TrainingSampleModel`'e upsert
    ettiği tek bir satır. Şu ana kadar uygulanan her kaynak için
    `chosen`/`rejected` tek kanatlıdır -- bir oy bir çiftin yalnızca bir
    tarafıdır, asla ikisi birden değil (bkz. `TrainingSampleModel`'in
    docstring'i); bir like için `rejected is None`, bir dislike için
    `chosen is None`.
    """

    source: str
    source_feedback_id: Optional[str]
    source_draft_id: Optional[str]
    prompt_context: str
    chosen: Optional[str]
    rejected: Optional[str]
    weight: float
    pair_hash: str


EXPLICIT_FEEDBACK_SOURCE = "explicit_feedback"


def pair_hash(company_id: str, source: str, identity: str) -> str:
    """Yeniden derlemenin (re-compile) upsert edeceği kimlik. `explicit_feedback`
    için `identity`, feedback satırının kendi id'sidir: bu satırın kimliği,
    `signal`'i değişse bile (yeniden oylama aynı satırı yerinde günceller,
    bkz. `FeedbackModel`'in docstring'i) tüm yaşam döngüsü boyunca sabittir,
    böylece bir 👍->👎 değişikliğinden sonra yeniden derleme, eski bir
    kopya bırakmak yerine aynı `training_samples` satırındaki
    `chosen`/`rejected`'i doğru şekilde tazeler.
    """
    return hashlib.sha256(f"{company_id}:{source}:{identity}".encode("utf-8")).hexdigest()


def _prompt_context(record: FeedbackRecord) -> str:
    parts: List[str] = []
    if record.correspondence_type:
        parts.append(f"Yazışma türü: {record.correspondence_type}")
    if record.confidence_score is not None:
        parts.append(f"Güven skoru: {record.confidence_score:.0f}")
    return " | ".join(parts)


def compile_pairs_from_feedback(
    company_id: str, records: Iterable[FeedbackRecord]
) -> List[PreferencePair]:
    """Çözümlenmiş feedback oylarını, her kayıt için bir tane olmak üzere tercih çiftlerine dönüştürür."""
    pairs: List[PreferencePair] = []
    for record in records:
        content = record.content.strip()
        if not content:
            continue
        is_like = record.signal == "like"
        pairs.append(
            PreferencePair(
                source=EXPLICIT_FEEDBACK_SOURCE,
                source_feedback_id=record.feedback_id,
                source_draft_id=record.draft_id,
                prompt_context=_prompt_context(record),
                chosen=content if is_like else None,
                rejected=None if is_like else content,
                weight=1.0,
                pair_hash=pair_hash(company_id, EXPLICIT_FEEDBACK_SOURCE, record.feedback_id),
            )
        )
    return pairs
