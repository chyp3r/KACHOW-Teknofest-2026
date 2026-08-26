"""Gelen resmi belgeler için zorunlu alan kuralları.

Kurallar bir veri dosyası yerine Python içinde tutulur, üç nedenle: Pydantic
onları import zamanında doğrular, bunlar kapalı, geliştirici tarafından
bakımı yapılan bir kümedir (`datasets/mevzuat/` altındaki düzenlenebilir
içerik olan mevzuat *metninin* aksine) ve grep/IDE navigasyonu her atfı
gerekçelendirdiği alanın hemen yanında tutar.

Madde numaraları, Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında
Yönetmelik'in resmi metninden (mevzuat.gov.tr'de yayımlanan) alınmıştır:
Başlık m.10, Sayı m.11, Tarih m.12, Konu m.13, Muhatap m.14, İlgi m.15,
Metin m.16, İmza m.17, Ek m.18, Gizlilik dereceli belgeler m.25.
"""

from pydantic import BaseModel, Field

from app.core.enums.document_type import DocumentType

SEVERITY_REQUIRED = "zorunlu"
SEVERITY_ADVISORY = "onerilen"

#: Atıflarda kullanılan yönetmelik kısa adları.
RYUEHY = "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik"
LAW_3071 = "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun"
LAW_4982 = "4982 sayılı Bilgi Edinme Hakkı Kanunu"

#: Her gelen belge türü için Türkçe görünen ad.
DOCUMENT_TYPE_LABELS: dict[DocumentType, str] = {
    DocumentType.OFFICIAL_LETTER: "Resmî Yazı",
    DocumentType.PETITION: "Dilekçe",
    DocumentType.INFORMATION_REQUEST: "Bilgi Edinme Başvurusu",
    DocumentType.COMPLAINT: "Şikayet",
    DocumentType.CIRCULAR: "Genelge",
    DocumentType.DIRECTIVE: "Talimat",
    DocumentType.REPORT: "Rapor",
    DocumentType.MINUTES: "Tutanak",
    DocumentType.LEAVE_REQUEST: "İzin Talebi",
    DocumentType.OTHER: "Diğer",
}

#: Her belge türü için mevzuat aramasını yönlendiren kelime dağarcığı.
#:
#: `REQUIRED_FIELD_RULES`'dan kasıtlı olarak ayrıdır, çünkü ikisi farklı
#: sorulara cevap verir. Kural tablosu *uygunluğa* cevap verir -- hangi
#: eksiklikler bu belgeyi tamamlanmamış yapar -- bu yüzden atıfları eksik bir
#: alanın karşısında raporlanan atıflardır. Bu eşleme ise *ilgililiğe* cevap
#: verir: bu belgenin bir okuyucusu hangi mevzuatın alıntılanmasını ister.
#: Bir izin talebi içeriği bakımından 657'ye tabidir, ama eksik bir 657
#: hükmü talebi tamamlanmamış yapmaz, bu yüzden 657 burada, orada değil yer
#: alır.
#:
#: Bu terimler arama sorgusuna eklenir çünkü hibrit alıcının BM25 yarısı
#: harfiyen token'larla eşleşir ve külliyat artık bir yerine yedi kanun
#: barındırıyor. Tek bir sabit ek, tek gerçek hedef yazışma yönetmeliğiyken
#: işe yarıyordu; genişletilmiş külliyat üzerinde ölçüldüğünde yönetmeliğin
#: kelime dağarcığını her sorguya koyuyor ve izin taleplerini ile
#: dilekçeleri, onları gerçekte yöneten kanunlardan uzaklaştırıyordu.
DOCUMENT_TYPE_QUERY_TERMS: dict[DocumentType, str] = {
    DocumentType.OFFICIAL_LETTER: "resmî yazışma usul esas sayı tarih konu ilgi imza",
    DocumentType.CIRCULAR: "resmî yazışma usul esas dağıtım sayı tarih konu imza",
    DocumentType.DIRECTIVE: "resmî yazışma usul esas talimat sayı tarih konu imza",
    DocumentType.MINUTES: "resmî yazışma usul esas tutanak tarih konu imza",
    DocumentType.REPORT: "resmî yazışma usul esas rapor tarih konu imza",
    DocumentType.PETITION: "dilekçe hakkı ad soyad imza adres başvuru",
    DocumentType.COMPLAINT: "dilekçe hakkı şikayet ad soyad imza adres başvuru",
    DocumentType.INFORMATION_REQUEST: "bilgi edinme hakkı başvuru usulü süre",
    DocumentType.LEAVE_REQUEST: "devlet memuru izin yıllık izin mazeret izni",
    DocumentType.OTHER: "resmî yazışma usul esas sayı tarih konu imza",
}


class FieldRule(BaseModel):
    """Bir belge türü için tek bir zorunlu-veya-önerilen alan gerekliliği."""

    key: str = Field(description="EvrakField üzerindeki alan adı.")
    label: str = Field(description="Alanın Türkçe adı.")
    severity: str = Field(description="'zorunlu' veya 'onerilen'.")
    mevzuat: str = Field(description="Alanı gerektiren mevzuat ve madde atfı.")
    reason: str = Field(description="Alanın neden gerekli olduğunun açıklaması.")


def _rule(
    key: str, label: str, mevzuat: str, reason: str, severity: str = SEVERITY_REQUIRED
) -> FieldRule:
    """Varsayılan önemi zorunlu olan bir `FieldRule` oluşturur.

    Args:
        key: `EvrakField` üzerindeki alan adı.
        label: Türkçe görünen ad.
        mevzuat: Mevzuat atfı.
        reason: Kısa Türkçe gerekçe.
        severity: `SEVERITY_REQUIRED` veya `SEVERITY_ADVISORY`.

    Returns:
        Oluşturulan kural.
    """
    return FieldRule(
        key=key, label=label, severity=severity, mevzuat=mevzuat, reason=reason
    )


# ---------- Ortak kural grupları ----------
_OFFICIAL_HEADER_RULES: tuple[FieldRule, ...] = (
    _rule(
        "sayi",
        "Sayı",
        f"{RYUEHY} m.11",
        "Belgelerde sayı bulunması zorunludur; belge takibi ve atıf sayı üzerinden yapılır.",
    ),
    _rule(
        "tarih",
        "Tarih",
        f"{RYUEHY} m.12",
        "Tarih, sayı ile aynı satırda yazı alanının en sağında bulunmalıdır.",
    ),
    _rule(
        "konu",
        "Konu",
        f"{RYUEHY} m.13",
        "Konu, belgenin içeriğini özetleyen yan başlık olarak bulunmalıdır.",
    ),
    _rule(
        "muhatap",
        "Muhatap",
        f"{RYUEHY} m.14",
        "Muhatap, belgenin gönderildiği idareyi veya kişiyi belirtir.",
    ),
    _rule(
        "gonderen_kurum",
        "Gönderen idare (başlık)",
        f"{RYUEHY} m.10",
        "Başlık, belgeyi gönderen idarenin adının belirtildiği bölümdür.",
    ),
    _rule(
        "imza_sahibi",
        "İmza sahibi",
        f"{RYUEHY} m.17",
        "Belge, yetkili amir tarafından ad ve soyad belirtilerek imzalanmalıdır.",
    ),
    _rule(
        "imza_unvani",
        "İmza sahibinin unvanı",
        f"{RYUEHY} m.17",
        "İmza bölümünde imzalayanın unvanı da yer almalıdır.",
        SEVERITY_ADVISORY,
    ),
)

_PETITION_RULES: tuple[FieldRule, ...] = (
    _rule(
        "basvuran_adi",
        "Başvuranın adı ve soyadı",
        f"{LAW_3071} m.4",
        "Dilekçede dilekçe sahibinin adı ve soyadı bulunması gerekir.",
    ),
    _rule(
        "imza_sahibi",
        "İmza",
        f"{LAW_3071} m.4",
        "Dilekçede dilekçe sahibinin imzası bulunması gerekir.",
    ),
    _rule(
        "adres",
        "İş veya ikametgâh adresi",
        f"{LAW_3071} m.4",
        "Dilekçede iş veya ikametgâh adresinin bulunması gerekir.",
    ),
    _rule(
        "konu",
        "Konu",
        f"{RYUEHY} m.13",
        "Talebin konusu açıkça belirtilmelidir.",
    ),
    _rule(
        "tarih",
        "Tarih",
        f"{RYUEHY} m.12",
        "Başvurunun tarihi, süre hesaplarında esas alınır.",
        SEVERITY_ADVISORY,
    ),
)

_INFORMATION_REQUEST_RULES: tuple[FieldRule, ...] = (
    _rule(
        "basvuran_adi",
        "Başvuranın adı ve soyadı",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda başvuru sahibinin adı ve soyadı bulunmalıdır.",
    ),
    _rule(
        "imza_sahibi",
        "İmza",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda başvuru sahibinin imzası bulunmalıdır.",
    ),
    _rule(
        "adres",
        "Oturma yeri veya iş adresi",
        f"{LAW_4982} m.6",
        "Bilgi edinme başvurusunda oturma yeri veya iş adresi bulunmalıdır.",
    ),
    _rule(
        "konu",
        "İstenen bilgi veya belge",
        f"{LAW_4982} m.6",
        "Başvuruda istenen bilgi veya belgenin açıkça belirtilmesi gerekir.",
    ),
    _rule(
        "iletisim",
        "İletişim bilgisi",
        f"{RYUEHY} m.24",
        "Başvuru sonucunun iletilebilmesi için iletişim bilgisi önerilir.",
        SEVERITY_ADVISORY,
    ),
)


REQUIRED_FIELD_RULES: dict[DocumentType, tuple[FieldRule, ...]] = {
    DocumentType.OFFICIAL_LETTER: _OFFICIAL_HEADER_RULES,
    DocumentType.CIRCULAR: _OFFICIAL_HEADER_RULES,
    DocumentType.DIRECTIVE: _OFFICIAL_HEADER_RULES,
    DocumentType.PETITION: _PETITION_RULES,
    DocumentType.COMPLAINT: _PETITION_RULES,
    DocumentType.INFORMATION_REQUEST: _INFORMATION_REQUEST_RULES,
    DocumentType.LEAVE_REQUEST: (
        _rule(
            "basvuran_adi",
            "Talep sahibinin adı ve soyadı",
            f"{LAW_3071} m.4",
            "İzin talebinde talep sahibinin adı ve soyadı bulunmalıdır.",
        ),
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Talebin konusu ve izin türü açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "İzin talebinin tarihi, izin süresinin hesaplanması için gereklidir.",
        ),
        _rule(
            "imza_sahibi",
            "İmza",
            f"{LAW_3071} m.4",
            "Talep, talep sahibi tarafından imzalanmalıdır.",
        ),
    ),
    DocumentType.MINUTES: (
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Tutanağın düzenlendiği tarih bulunmalıdır.",
        ),
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Tutanağın konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "imza_sahibi",
            "İmza sahibi",
            f"{RYUEHY} m.17",
            "Tutanak, düzenleyen görevliler tarafından imzalanmalıdır.",
        ),
    ),
    DocumentType.REPORT: (
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Raporun konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Raporun tarihi bulunmalıdır.",
        ),
        _rule(
            "imza_sahibi",
            "İmza sahibi",
            f"{RYUEHY} m.17",
            "Rapor, düzenleyen tarafından imzalanmalıdır.",
        ),
    ),
    # Tanınmayan bir belge için bile en az kimlik belirleyici alanlar kontrol
    # edilir, böylece bilinmeyen bir tür asla sessizce tam uygun olarak
    # raporlanmaz.
    DocumentType.OTHER: (
        _rule(
            "konu",
            "Konu",
            f"{RYUEHY} m.13",
            "Belgenin konusu açıkça belirtilmelidir.",
        ),
        _rule(
            "tarih",
            "Tarih",
            f"{RYUEHY} m.12",
            "Belgenin tarihi bulunmalıdır.",
            SEVERITY_ADVISORY,
        ),
    ),
}


#: Bir alan yokken bir dil modelinin null yerine ürettiği değerler. Türkçe
#: duyarlı büyük/küçük harf indirgemesinden sonra karşılaştırılır, bu yüzden
#: her giriş zaten indirgenmiş biçimde olmalıdır (küçük harf ASCII,
#: noktalama sadeleştirilmiş). "-" veya "N/A" gibi sadece noktalamadan
#: oluşan yer tutucular sırasıyla "" ve "n a"ya indirgenir, bu yüzden ayrı
#: bir girişe ihtiyaç duymazlar.
BLANK_VALUE_MARKER: frozenset[str] = frozenset(
    {
        "",
        "yok",
        "n a",
        "na",
        "bilinmiyor",
        "belirtilmemis",
        "belirtilmedi",
        "bulunmuyor",
        "bulunmamaktadir",
        "mevcut degil",
        "bos",
        "null",
        "none",
        "nan",
        "tespit edilemedi",
        "okunamadi",
        "yazilmamis",
    }
)
