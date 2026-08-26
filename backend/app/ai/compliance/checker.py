import logging
import re
import unicodedata
from typing import Any, Optional

from app.ai.compliance.evrak_field import ComplianceReport, EvrakField, MissingField
from app.ai.compliance.field_rule import (
    BLANK_VALUE_MARKER,
    REQUIRED_FIELD_RULES,
    RYUEHY,
    SEVERITY_ADVISORY,
    SEVERITY_REQUIRED,
    FieldRule,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType

logger = logging.getLogger(__name__)

_TURKISH_FOLD = str.maketrans(
    {
        "ç": "c",
        "Ç": "c",
        "ğ": "g",
        "Ğ": "g",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "Ö": "o",
        "ş": "s",
        "Ş": "s",
        "ü": "u",
        "Ü": "u",
    }
)


def normalize_value(value: Any) -> str:
    """Belirteç karşılaştırmasını deterministik yapmak için değeri küçük harf ASCII'ye indirger.

    Türkçe karakterler, Unicode normalizasyonundan önce açıkça çevrilir çünkü
    `str.lower()` "I" harfini "i"ye eşler ama "İ" harfini iki kod noktalı bir
    dizi olarak bırakır; bu da Türkçe harflerle yazılmış belirteçlerin
    kaçırılmasına yol açar.

    Args:
        value: Herhangi bir değer; string olmayanlar stringe çevrilir.

    Returns:
        İndirgenmiş, boşlukları sadeleştirilmiş gösterim.
    """
    text = str(value).translate(_TURKISH_FOLD)
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def is_blank(value: Any) -> bool:
    """Çıkarılan bir alan değerinin boş sayılıp sayılmadığını bildirir.

    None, boş veya sadece boşluktan oluşan string'leri, boş listeleri ve
    `BLANK_VALUE_MARKER` içindeki yer tutucu ifadeleri boş kabul eder. Eksik
    bir alan sorulduğunda bir dil modeli genellikle null yerine "Belirtilmemiş"
    veya "-" yanıtı verir; bunları olduğu gibi kabul etmek her belgeyi eksiksiz
    olarak raporlamaya yol açar.

    Args:
        value: Çıkarılan alan değeri.

    Returns:
        Değer hiçbir bilgi taşımıyorsa True.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return normalize_value(value) in BLANK_VALUE_MARKER


def _rules_for(document_type: DocumentType | str) -> tuple[FieldRule, ...]:
    """Bir belge türü için kural setini çözer, bulunamazsa OTHER'a döner.

    Args:
        document_type: Sınıflandırılmış belge türü veya ham değeri.

    Returns:
        Uygulanacak kurallar.
    """
    try:
        resolved = DocumentType(document_type)
    except ValueError:
        logger.warning(
            "Unknown document type %r; falling back to %s rules.",
            document_type,
            DocumentType.OTHER.value,
        )
        resolved = DocumentType.OTHER
    return REQUIRED_FIELD_RULES.get(
        resolved, REQUIRED_FIELD_RULES[DocumentType.OTHER]
    )


def check_required_fields(
    document_type: DocumentType | str,
    fields: EvrakField,
    is_signed: Optional[bool] = None,
) -> ComplianceReport:
    """Çıkarılan bir belgede hangi zorunlu alanların eksik olduğunu belirler.

    Bir kural tablosu üzerinde saf küme çıkarma işlemidir — hiçbir dil modeli
    devreye girmez, bu yüzden sonuç her çalıştırmada bayt bayt aynıdır ve her
    alıntı tam olarak doğrudur.

    Args:
        document_type: Gelen belgenin sınıflandırılmış türü.
        fields: Belgeden çıkarılan alanlar.
        is_signed: Belgede imza şeklinde bir mürekkep izinin tespit edilip
            edilmediği (`app.infrastructure.extractors.marks.detect_marks`,
            `DocumentAnalysisState.detected_marks` üzerinden aktarılır).
            Tespit hiç çalışmadıysa (ör. rasterize edilmeyen, doğuştan
            dijital bir PDF) `None` olur — bu, bu modülün mevcut "asla tahmin
            etme" duruşuna uygun şekilde imzasız değil, bilinmiyor olarak ele
            alınır (bkz. `is_blank`'ın kendi docstring'i). Bunun aslında neyi
            kapı gibi kontrol ettiğini görmek için aşağıdaki "İmza görseli"
            kontrolüne bakın.

    Returns:
        Yasal dayanaklarıyla birlikte eksik alanlar ve genel durum.
    """
    rules = _rules_for(document_type)
    missing: list[MissingField] = []

    for rule in rules:
        value = getattr(fields, rule.key, None)
        if is_blank(value):
            missing.append(
                MissingField(
                    key=rule.key,
                    label=rule.label,
                    severity=rule.severity,
                    mevzuat=rule.mevzuat,
                    reason=rule.reason,
                )
            )

    # Ek niteliğinde ve kasıtlı olarak dar kapsamlı: yukarıdaki imza_sahibi
    # kuralının göremediği boşluğu yakalar. Sayfa aslında hiç imzalanmamış
    # olsa bile *yazılmış* bir isim o kuralı sağlar (fields.imza_sahibi boş
    # değildir) -- tam olarak taranmış, gerçekten imzasız bir çıktının
    # ürettiği durum budur. Sadece bu özel boşlukta tetiklenir (isim var,
    # tespit edilen iz yok); imza_sahibi zaten boşsa yukarıdaki kural bunu
    # zaten raporlar ve burada tekrar etmek sinyal değil gürültü olurdu.
    # Zorunlu değil, tavsiye niteliğindedir: sezgisel bir dedektörün yanlış
    # negatifi (bunun neden yasal bir belirleme değil de bir inceleme ipucu
    # olduğuna dair marks.py'nin kendi modül docstring'ine bakın) tek
    # başına, aksi halde eksiksiz bir belgeyi "eksik" olarak işaretleyemez.
    if (
        is_signed is False
        and not is_blank(getattr(fields, "imza_sahibi", None))
        and any(rule.key == "imza_sahibi" for rule in rules)
    ):
        missing.append(
            MissingField(
                key="imza_gorseli",
                label="İmza görseli",
                severity=SEVERITY_ADVISORY,
                mevzuat=f"{RYUEHY} m.17",
                reason=(
                    "Belgede imza sahibinin adı yer alıyor ancak sayfada bir "
                    "imza taranmadı; belgenin gerçekten imzalanmış bir "
                    "nüshasının yüklendiğini doğrulayın."
                ),
            )
        )

    if not missing:
        status = ComplianceStatus.COMPLIANT
    elif any(item.severity == SEVERITY_REQUIRED for item in missing):
        status = ComplianceStatus.INCOMPLETE
    else:
        status = ComplianceStatus.PARTIALLY_COMPLIANT

    logger.info(
        "Compliance check for %s: %s (%d/%d field(s) missing).",
        document_type,
        status.value,
        len(missing),
        len(rules),
    )
    return ComplianceReport(
        status=status, missing_fields=missing, checked_field_count=len(rules)
    )
