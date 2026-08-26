"""Gizlilik damgasını, PII bulgularını ve enjeksiyon işaretlerini tek bir
girdi tarafı hassasiyet değerlendirmesinde birleştirir.

Zaten çıkarılmış veriler (``EvrakField``, PII bulguları, enjeksiyon temizleme
işaretleri) üzerinde çalışan saf bir fonksiyon -- I/O yok, model çağrısı yok,
``app.ai.verification.draft_verifier.verify_draft`` ile aynı şekilde birim
test edilebilir: girdiler verildiğinde, tek bir deterministik karar.
"""

import unicodedata
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.compliance.evrak_field import EvrakField
from app.ai.guardrails.pii import PiiFinding, find_pii
from app.ai.policy import GuardrailPolicy, get_policy
from app.core.enums.sensitivity_level import LABEL_ALIASES, SensitivityLevel

#: ``app.ai.guardrails.injection._fold`` ve
#: ``app.ai.verification.normalizers._fold`` ile aynı katlama tekniği --
#: her guardrail/doğrulama modülü, modül sınırları arasında özel bir
#: yardımcıyı paylaşmak yerine kendi kopyasına sahip; bu codebase'in mevcut
#: kuralıyla uyumlu.
_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


def _fold(text: str) -> str:
    """Etiket eşleştirmesi için Türkçe metni küçük harf ASCII'ye katlar."""
    translated = (text or "").translate(_TURKISH_MAP)
    normalized = unicodedata.normalize("NFKD", translated)
    return normalized.encode("ascii", "ignore").decode("ascii").lower().strip()


def _level_from_label(label: Optional[str]) -> SensitivityLevel:
    """Serbest metin bir ``gizlilik_derecesi`` değerini ``SensitivityLevel``'a eşler.

    Args:
        label: Belgeden okunan ham değer (örn. "Hizmete Özel"), veya belge
            hiç gizlilik damgası taşımıyorsa None.

    Returns:
        Eşleşen derece, ya da etiket yoksa veya bilinen bir dereceyle
        eşleşmiyorsa ``UNMARKED`` -- tanınmayan bir etiket hiçbir şeyin
        kanıtı değildir, bu yüzden sessizce yükseltilmemelidir.
    """
    if not label:
        return SensitivityLevel.UNMARKED
    return LABEL_ALIASES.get(_fold(label), SensitivityLevel.UNMARKED)


class SensitivityAssessment(BaseModel):
    """Bir belge için girdi tarafı guardrail kararı."""

    level: SensitivityLevel = Field(
        description=(
            "Belgeden çıkarılan HAM gizlilik derecesi -- belgede hiç damga "
            "yoksa UNMARKED, denetim izi için asla üzerine yazılmaz."
        )
    )
    effective_level: SensitivityLevel = Field(
        default=SensitivityLevel.UNMARKED,
        description=(
            "Erişim denetimi ve tüm diğer kararlarda fiilen kullanılan "
            "derece -- level UNMARKED ise policy.default_sensitivity_level'a "
            "otomatik atanır, aksi halde level ile aynıdır."
        ),
    )
    is_defaulted: bool = Field(
        default=False,
        description="effective_level, belgede hiç damga olmadığı için varsayılan atandıysa True.",
    )
    pii_findings: list[PiiFinding] = Field(default_factory=list)
    requires_review: bool = Field(
        description="Gizlilik derecesi (effective_level) politika eşiğini aşıyorsa True."
    )
    reasons: list[str] = Field(default_factory=list)


def assess(
    *,
    fields: EvrakField,
    text: str = "",
    scrub_markers: Sequence[str] = (),
    policy: Optional[GuardrailPolicy] = None,
) -> SensitivityAssessment:
    """Bir belgenin hassasiyetini, ayrıştırılmış alanlarından ve ham metninden değerlendirir.

    Args:
        fields: Belgenin çıkarılmış ``EvrakField``'ı (``gizlilik_derecesi``'ni okur).
        text: PII kalıpları için taranan, çıkarılmış belge metni.
        scrub_markers: ``app.ai.guardrails.injection.scrub_extracted_text``
            tarafından zaten bulunmuş enjeksiyon temizleme işaretleri; bir
            çağrı noktasının (``DocumentService``) bir belgenin tetiklediği
            her şeyi tek bir yerde loglayabilmesi için reasons listesine
            katlanır.
        policy: Karşılaştırılacak guardrail politikası. Varsayılan olarak
            süreç politikası kullanılır.

    Returns:
        Birleşik değerlendirme. ``requires_review`` yalnızca gizlilik
        derecesini yansıtır (çözümlenmiş politikaya göre: damgalı bir
        Gizli/Çok Gizli belge, düşük güvenli bir taslakla aynı şekilde
        insan incelemesine yönlendirilir) -- aynı politikaya göre PII tek
        başına engellemeden işaretlenir.
    """
    active_policy = policy or get_policy().guardrail

    level = _level_from_label(fields.gizlilik_derecesi)
    is_defaulted = level is SensitivityLevel.UNMARKED
    effective_level = active_policy.default_sensitivity_level if is_defaulted else level
    findings = [
        finding
        for finding in find_pii(text)
        if finding.confidence >= active_policy.pii_confidence_floor
    ]

    reasons: list[str] = []
    if level is not SensitivityLevel.UNMARKED:
        reasons.append(f"gizlilik_derecesi: {fields.gizlilik_derecesi}")
    elif is_defaulted:
        reasons.append(
            "gizlilik derecesi belgede belirtilmemiş; en düşük dereceye "
            f"({effective_level.value}) otomatik atandı"
        )
    if findings:
        kinds = ", ".join(sorted({finding.kind for finding in findings}))
        reasons.append(f"{len(findings)} pii bulgusu ({kinds})")
    if scrub_markers:
        reasons.append(f"{len(scrub_markers)} enjeksiyon işareti temizlendi")

    requires_review = effective_level in active_policy.sensitivity_block_levels

    return SensitivityAssessment(
        level=level,
        effective_level=effective_level,
        is_defaulted=is_defaulted,
        pii_findings=findings,
        requires_review=requires_review,
        reasons=reasons,
    )


def assessment_from_analysis(analysis: dict[str, Any]) -> SensitivityAssessment:
    """Bir sınıflandırma dict'inden bir ``SensitivityAssessment`` yeniden inşa eder.

    Bu turda ``planning_graph._run_classification``'ın hangi yolu izlediğine
    bağlı olarak bu fonksiyona iki farklı şekil ulaşır: canlı bir
    ``document_analysis_graph`` çağrısı, değerlendirmeyi bu modülün kendi
    alan adlarıyla (``level``, ``requires_review``) ``sensitivity_assessment``
    altında taşır; önbellekten gelen yol ise aynı bilgiyi API'ye dönük
    şemanın alan adlarıyla (``sensitivity_level``, ``requires_human_review``)
    ``guardrail`` altında taşıyan derlenmiş bir ``DocumentAnalysisResponseSchema``
    dökümü döndürür -- bkz. ``app.domains.documents.schema.document_schema``
    içindeki ``GuardrailAssessmentSchema``. Çağıranların (``_run_assist``,
    ``output_gate.evaluate_response``) elindeki dict'i hangi yolun ürettiğini
    bilmesine gerek kalmasın diye ikisi de burada okunur.

    Args:
        analysis: Yukarıdaki şekillerden birinde bir sınıflandırma/analiz dict'i.

    Returns:
        Yeniden inşa edilen değerlendirme. Eksik veya tanınmayan veri, hata
        fırlatmak yerine sorunsuz bir ``UNMARKED`` değerlendirmesine
        düşürülür -- hatalı biçimlendirilmiş veya olmayan bir değerlendirme
        asla kendisi bir yanıtın engellenme nedeni olmamalıdır.
    """
    raw = analysis.get("guardrail") or analysis.get("sensitivity_assessment") or {}

    level_raw = raw.get("sensitivity_level", raw.get("level", SensitivityLevel.UNMARKED.value))
    try:
        level = SensitivityLevel(level_raw)
    except ValueError:
        level = SensitivityLevel.UNMARKED

    # Daha eski önbellekli analizler (effective_level var olmadan önce
    # yazılmış) böyle bir anahtar taşımaz -- hata fırlatmak veya sessizce
    # engellemek yerine, belge hiç varsayılana düşürülmemiş gibi `level`in
    # kendisine döner.
    effective_level_raw = raw.get("effective_sensitivity_level", raw.get("effective_level"))
    try:
        effective_level = (
            SensitivityLevel(effective_level_raw) if effective_level_raw is not None else level
        )
    except ValueError:
        effective_level = level
    is_defaulted = bool(
        raw.get("sensitivity_is_defaulted", raw.get("is_defaulted", False))
    )

    pii_findings = [
        PiiFinding(**item) if isinstance(item, dict) else item
        for item in raw.get("pii_findings") or []
    ]
    requires_review = bool(raw.get("requires_human_review", raw.get("requires_review", False)))
    reasons = list(raw.get("reasons") or [])

    return SensitivityAssessment(
        level=level,
        effective_level=effective_level,
        is_defaulted=is_defaulted,
        pii_findings=pii_findings,
        requires_review=requires_review,
        reasons=reasons,
    )
