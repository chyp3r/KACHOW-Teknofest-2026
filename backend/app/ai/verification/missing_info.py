"""Bir taslaktaki doldurulmamış yer tutucuları insana sorulabilir bir isteğe dönüştürür.

Kasıtlı olarak deterministik ve LLM kullanmıyor: eksik bilgi isteği, Görev 2'nin
"gerekli durumlarda eksik bilgi talep edebilmesi" gereksiniminin HITL
tetikleyicisidir ve aynı taslak için her seferinde -- devam (resume) yolunda
taslağın yeniden üretilmediği durum dahil -- aynı soruları üretmelidir.

Bu modül hem taslak (``draft_graph``) hem revizyon (``revise_graph``) akışının
paylaştığı ``human_gate`` yoludur; iki akışın kullanıcıya sorduğu eksik-alan
sorusu aynı biçimde -- açıklayıcı bir soru kalıbı, "bu alan nedir / neden
gerekli" yardımı ve mümkünse bir örnek ile -- üretilir. ``build_missing_info_request``
ayrıca daha önce (bir önceki gate turunda ya da yerleşmiş yazım briefinde)
çözülmüş yer tutucuları atlar, böylece revizyon, taslak turunda zaten verilmiş
bir bilgiyi tekrar sormaz.
"""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, VerificationReport, _fold
from app.ai.verification.placeholders import _DATE_LINE_PATTERN
from app.ai.workflows.writing_brief import AUTO_ANSWER

logger = logging.getLogger(__name__)


class InfoQuestion(BaseModel):
    """İnsanın sağlaması gereken tek bir bilgi parçası."""

    key: str = Field(description="Bu yer tutucuyu resume çağrıları arasında tanımlayan sabit slug.")
    label: str = Field(description="Kullanıcıya gösterilen, taslaktan aynen alınmış yer tutucu metni.")
    why: str = Field(
        default="",
        description=(
            "Bu alanın ne olduğunu ve neden gerekli olduğunu açıklayan yardım metni. "
            "Bir compliance kuralına eşleştiğinde hukuki/mevzuat gerekçesi, aksi halde "
            "alanın genel bir tarifi -- her iki durumda da dolu olmalıdır."
        ),
    )
    example: str | None = Field(default=None, description="Mümkün olduğunda alana örnek bir değer.")
    required: bool = Field(default=True)

    def to_prompt_question(self) -> dict[str, Any]:
        """Emit sınırı için kanonik ``PromptQuestion`` biçimine dönüştürür.

        ``InfoQuestion``, dahili olarak her yerde kullanılan tip olmaya devam
        eder -- ``apply_answers``/``_slugify`` ve resume sözleşmesinin tamamı
        ``key`` üzerinden eşleşir -- bu dönüşüm yalnızca ``human_gate_node``'un
        emit çağrısında çalışır, böylece tek bir frontend kart bileşeni bunu
        writing-brief ve clarify sorularıyla birlikte render edebilir.
        ``key`` bayt bayt aynen taşınır: ``apply_answers``'ın yer tutucuları
        yerine koyarken kullandığı join anahtarı budur.
        """
        return {
            "key": self.key,
            "question": f"'{self.label}' alanı için ne yazılmalı?",
            "header": self.label,
            "help": self.why,
            "example": self.example,
            "options": [],
            "multi_select": False,
            "allow_free_text": True,
            "required": self.required,
        }


def _slugify(text: str) -> str:
    """Yer tutucu metnini sabit, tekrar üretilebilir bir cevap anahtarına indirger."""
    slug = _fold(text).replace(" ", "_")
    return slug or "bilgi"


def _match_missing_field(
    label_text: str, missing_fields: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Bu yer tutucunun büyük olasılıkla işaret ettiği compliance-node MissingField'ı bulur."""
    folded_label = _fold(label_text)
    if not folded_label:
        return None
    for field in missing_fields:
        field_label = _fold(str(field.get("label", "")))
        field_key = _fold(str(field.get("key", "")))
        if field_label and (field_label in folded_label or folded_label in field_label):
            return field
        if field_key and field_key in folded_label:
            return field
    return None


#: Yerleşmiş yazım-briefi (``app.ai.workflows.writing_brief``) slot anahtarı ->
#: bu slotun cevabıyla güvenle doldurulabilecek yer tutucuların katlanmış
#: (``_fold``) metin parçaları. Yalnızca serbest-metin, katalogsuz slotlar
#: buradadır (``muhatap`` / ``yazan_taraf``): bunların cevabı gerçek bir
#: kurum/kişi adıdır. ``imza`` / ``sayi`` gibi katalog sahibi slotların cevabı
#: bir seçenek değeri sentineli (``"yer_tutucu"`` vb.) olduğundan metne
#: yerleştirilemez, bu yüzden dışarıda bırakılmıştır.
_BRIEF_SLOT_ALIASES: dict[str, tuple[str, ...]] = {
    "muhatap": (
        "muhatap",
        "alicinin adi",
        "alici adi",
        "gonderilecek makam",
        "gonderilecegi makam",
        "yazinin gonderilecegi",
    ),
    "yazan_taraf": (
        "gonderen kurum",
        "gonderen kurumun adi",
        "gonderen makam",
        "yazan taraf",
        "kurumumuzun adi",
    ),
}


#: Bir compliance kuralına eşleşmeyen yer tutucular için genel açıklama tablosu:
#: ``(katlanmış metin parçaları, yardım metni, örnek | None)``. Sıra önemlidir --
#: ilk eşleşen kazanır, bu yüzden daha özgül girdiler önce gelir.
_GENERIC_FIELD_HELP: tuple[tuple[tuple[str, ...], str, str | None], ...] = (
    (
        ("belge sayisi", "evrak sayisi", "sayi no", "sayi numarasi", "dosya sayisi"),
        "Belgenin resmî kayıt sayısı. Belge takibi ve sonraki yazışmalardaki atıflar bu "
        "sayı üzerinden yapılır; resmî yazıda sayı bulunması zorunludur.",
        "E-12345678-100-4567",
    ),
    (
        ("imza sahibi", "imzalayacak yetkili", "imzalayacak yetkilinin adi", "yetkili amir", "imza blogu"),
        "Belgeyi imzalayacak yetkilinin adı, soyadı ve unvanı. Resmî yazı, yetkili amir "
        "tarafından ad ve unvan belirtilerek imzalanır.",
        "Ahmet Yılmaz / Daire Başkanı",
    ),
    (
        ("muhatap", "alicinin adi", "alici adi", "gonderilecek makam", "gonderilecegi makam"),
        "Yazının resmî olarak gönderileceği kurum, birim veya kişi. Resmî yazışmada muhatap "
        "satırı zorunludur ve yazının kime hitaben yazıldığını belirler.",
        "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı",
    ),
    (
        ("konu",),
        "Yazının konusunu bir iki kelimeyle özetleyen başlık. Konu satırı muhatabın yazıyı "
        "hızlıca sınıflandırmasını sağlar.",
        "Yıllık izin talebi",
    ),
    (
        ("acik adres", "posta adresi", "adres"),
        "Kurumun veya kişinin açık posta adresi.",
        None,
    ),
    (
        ("telefon", "iletisim", "e posta", "eposta", "e-posta"),
        "İletişim için telefon numarası veya e-posta adresi.",
        None,
    ),
    (
        ("tarih",),
        "Alana yazılacak tarih (gün.ay.yıl biçiminde).",
        "01.01.2026",
    ),
)


def _generic_field_help(label_text: str) -> tuple[str, str | None]:
    """Bir yer tutucu için genel (compliance dışı) yardım metni ve örneği.

    Bilinen bir alan şekline eşleşmezse bile **boş olmayan** bir açıklama
    döndürür -- taslak akışının aksine revizyon akışının tek alan-sorma
    yüzeyi budur, dolayısıyla kullanıcı hiçbir durumda bağlamsız bir kutuyla
    baş başa kalmamalıdır.
    """
    folded = _fold(label_text)
    for fragments, help_text, example in _GENERIC_FIELD_HELP:
        if any(fragment in folded for fragment in fragments):
            return help_text, example
    return (
        f"Taslakta '{label_text}' alanı boş bırakılmış. Bu alana ne yazılması gerektiğini "
        f"belirtin; sistem verdiğiniz değeri metindeki yer tutucunun yerine koyacaktır. Emin "
        f"değilseniz 'Sen karar ver' seçeneğini işaretleyebilirsiniz.",
        None,
    )


def resolve_placeholders_from_brief(
    draft: str, writing_brief: dict[str, Any] | None
) -> dict[str, str]:
    """Yerleşmiş yazım briefinden doldurulabilecek yer tutucuları çözer.

    Bir sonraki ``revize`` turunda, taslak turunda zaten toplanmış bir
    ``[Muhatap]`` / ``[Gönderen kurum]`` gibi bir yer tutucuyu kullanıcıya
    tekrar sormak yerine brief cevabından doldurmak için kullanılır.

    Args:
        draft: İçinde ``[...]`` yer tutucuları olabilecek taslak metni.
        writing_brief: Yerleşmiş yazım-briefi slot cevapları (slot ``key``'i
            ile anahtarlanmış).

    Returns:
        ``InfoQuestion.key`` -> brief'ten gelen gerçek değer. Yalnızca gerçek
        bir metin değeri taşıyan girdiler döner; ``AUTO_ANSWER`` sentineli
        ("Sen karar ver") asla dahil edilmez.
    """
    if not writing_brief:
        return {}
    resolved: dict[str, str] = {}
    for match in PLACEHOLDER_PATTERN.finditer(draft):
        placeholder_text = match.group(0).strip("[]").strip()
        if not placeholder_text:
            continue
        key = _slugify(placeholder_text)
        if key in resolved:
            continue
        folded = _fold(placeholder_text)
        for slot_key, fragments in _BRIEF_SLOT_ALIASES.items():
            if not any(fragment in folded for fragment in fragments):
                continue
            value = writing_brief.get(slot_key)
            if isinstance(value, str) and value.strip() and value != AUTO_ANSWER:
                resolved[key] = value.strip()
            break
    return resolved


def build_missing_info_request(
    draft: str,
    report: VerificationReport,
    classification: dict[str, Any] | None = None,
    *,
    resolved_keys: dict[str, Any] | None = None,
    writing_brief: dict[str, Any] | None = None,
) -> list[InfoQuestion]:
    """Taslaktaki her ayrı ``[...]`` yer tutucusu için bir soru üretir.

    Args:
        draft: Üretilmiş taslak metni.
        report: Deterministik doğrulama raporu (bugün doğrudan kullanılmıyor,
            gelecekte bir yapısal kontrolün, çağrıları değiştirmeden hangi
            yer tutucuların gerçekten sorulacağını belirleyebilmesi için
            imzada tutuluyor).
        classification: Analiz sonucu; bir yer tutucu eşleştiğinde ``why``
            gerekçesini ``missing_fields`` alanından sağlar.
        resolved_keys: Daha önceki bir gate turunda çözülmüş ya da "Sen karar
            ver" ile ertelenmiş yer tutucu anahtarları (``InfoQuestion.key`` ->
            değer veya ``AUTO_ANSWER``). Bu anahtarlar için tekrar soru
            üretilmez -- revizyon akışının, taslak turunda zaten verilmiş bir
            bilgiyi yeniden sormasını engeller.
        writing_brief: Yerleşmiş yazım-briefi cevapları; ``[Muhatap]`` gibi
            buradan doldurulabilecek yer tutucular için soru üretilmez (çağıran
            tarafında ön-doldurulur).

    Returns:
        Taslaktaki sırayla, her ayrı yer tutucu için bir :class:`InfoQuestion`.
    """
    del report  # gelecekteki bir yapısal filtre için ayrılmıştır; bugün gerekli değil
    missing_fields = (classification or {}).get("missing_fields") or []
    resolved_keys = resolved_keys or {}
    brief_resolved = resolve_placeholders_from_brief(draft, writing_brief)
    seen: dict[str, InfoQuestion] = {}

    # Cevabın kendi "Tarih:" başlık satırı, hiçbir zaman gerçek bir bilgi
    # eksikliği olmayan tek yer tutucudur: app.ai.verification.placeholders.
    # fill_date_placeholders bu kod çalışmadan önce (bkz. draft_graph.verify_node /
    # revise_graph.verify_node) onu sunucu tarafından çözümlenmiş tarihle
    # doldurmayı zaten denemiştir, dolayısıyla bunu sormak kullanıcıya,
    # sistemin -- kullanıcının değil -- sorumlu olduğu bir bilgiyi sormak
    # olurdu. Bu, `_DATE_LINE_PATTERN`'in eşleştiği tam yapısal satıra
    # sabitlenmiştir -- daha önce kullanılan çıplak "katlanmış metin tarih
    # ile başlıyor mu" alt dizge testi DEĞİL: o test, tarihle etiketlenmiş
    # ama ilgisiz diğer yer tutucuları da (örn. "[Başvuru Tarihi]", "[Son
    # Başvuru Tarihi]", satır içi "[Tarih Aralığı]") sessizce yutup hiç
    # sorulmamalarına yol açıyordu; bu tür bir atlama yapmayan apply_answers
    # ise resume sırasında aynı yer tutucuyu yine de cevaplanmamış
    # ("residual") olarak sayıyordu. Bu ikisinin uyuşmazlığı, `missing_information`
    # listesi boş olan bir NEEDS_INPUT turu üretiyordu: içinde sıfır soru
    # olan bir kesinti (interrupt) -- insanın cevaplamasının bir yolu, kapının
    # da (gate) bundan çıkmasının bir yolu yoktu (bkz. human_gate_node'un
    # kendi `residual_questions` filtresi, bu düzeltmenin diğer yarısı).
    date_header_spans = [match.span() for match in _DATE_LINE_PATTERN.finditer(draft)]

    def _is_date_header(match: "re.Match[str]") -> bool:
        return any(
            start <= match.start() and match.end() <= end
            for start, end in date_header_spans
        )

    for match in PLACEHOLDER_PATTERN.finditer(draft):
        placeholder_text = match.group(0).strip("[]").strip()
        if not placeholder_text:
            continue
        if _is_date_header(match):
            continue
        key = _slugify(placeholder_text)
        if key in seen:
            continue
        # Taslak turunda zaten çözülmüş / "Sen karar ver" ile ertelenmiş, ya da
        # yerleşmiş yazım briefinden doldurulabilecek bir yer tutucu tekrar
        # sorulmaz -- iki akış (taslak <-> revizyon) arasındaki "aynı şeyi iki
        # kez sorma" tutarsızlığının düzeltmesi.
        if key in resolved_keys:
            continue
        if key in brief_resolved:
            continue

        field = _match_missing_field(placeholder_text, missing_fields)
        why = ""
        example: str | None = None
        if field and (str(field.get("mevzuat", "")).strip() or str(field.get("reason", "")).strip()):
            why = f"{field.get('mevzuat', '')} -- {field.get('reason', '')}".strip(" -")
            example = field.get("example") or _generic_field_help(placeholder_text)[1]
        else:
            # Compliance eşleşmesi yok -> genel açıklama; ``why`` yine de dolu.
            why, example = _generic_field_help(placeholder_text)

        seen[key] = InfoQuestion(key=key, label=placeholder_text, why=why, example=example)

    return list(seen.values())


def _coerce_answer(value: object) -> str:
    """Bir resume cevabını düz bir dizgeye indirger, çoklu seçim listesini birleştirir.

    ``ChatResumeRequest.answers``, multi_select bir PromptQuestion'ın cevabını
    taşıyabilmek için ``dict[str, str | list[str]]``'a genişletildi (bkz.
    app.ai.workflows.event_schema.PromptQuestion) -- bugün hiçbir
    eksik-bilgi sorusu multi_select değil, ama bu durum bir gün değişirse
    ``apply_answers``'ı doğru tutar; birleştirme, yer tutucu metnine sızabilecek
    gizli bir ayraç yerine sade bir şekilde yapılır.
    """
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")


def apply_answers(draft: str, answers: dict[str, Any]) -> tuple[str, list[str]]:
    """Cevaplanan yer tutucuları, taslağı yeniden üretmeden içine geri yerleştirir.

    Args:
        draft: ``[...]`` yer tutucuları içeren taslak metni.
        answers: Bu taslağın ürettiği :class:`InfoQuestion` ``key``'i ile
            anahtarlanmış cevaplar.

    Returns:
        Yerine konmuş taslak ve hâlâ doldurulmamış yer tutucu anahtarlarının listesi.
    """
    residual: list[str] = []

    def _replace(match: "re.Match[str]") -> str:
        placeholder_text = match.group(0).strip("[]").strip()
        key = _slugify(placeholder_text)
        raw_answer = answers.get(key)
        if raw_answer == AUTO_ANSWER:
            # "Sen karar ver" (frontend'de "acceptAllDefaults") --
            # kullanıcı bu değeri sağlamayı açıkça reddetti, dolayısıyla bu
            # ne gerçek bir cevaptır (bekçi (sentinel) metninin kendisi asla
            # mektuba yerleştirilmemeli) ne de yeniden sorulacak cevaplanmamış
            # bir sorudur (kullanıcının tam da kapatmaya çalıştığı turu yeniden
            # açacağından `residual`'a asla eklenmemeli). Köşeli parantezli
            # yer tutucu, yazarın bıraktığı haliyle bırakılır -- insan bir
            # incelemecinin hâlâ görebileceği, görünür, metin içi bir işaret;
            # `writer.md`'nin kendi `[BİLGİ EKSİK: ...]` yer tutucularının
            # kullandığı aynı gelenek -- sessizce yutulmaz veya anlamsız bir
            # metinle değiştirilmez.
            return match.group(0)
        answer = _coerce_answer(raw_answer).strip()
        if answer:
            return answer
        residual.append(key)
        return match.group(0)

    substituted = PLACEHOLDER_PATTERN.sub(_replace, draft)
    if residual:
        logger.info("apply_answers left %d placeholder(s) unfilled.", len(residual))
    return substituted, residual
