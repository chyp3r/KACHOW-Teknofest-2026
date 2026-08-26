"""Belge türü sınıflandırmasını bilgilendirmek için kullanılan deterministik yapısal sinyaller.

Resmi bir kurum yazısı, düzenli ifadelerle ucuza tespit edilebilen ve model
değerlendirmesi gerektirmeyen, hataya yer bırakmayan yapısal işaretler taşır --
"T.C." başlığı, bir "Sayı:" alanı, unvanlı bir imza bloğu. Bunları sınıflandırıcı
prompt'una olgusal gözlemler olarak beslemek, bir kurum yazısı ile bir vatandaş
dilekçesi arasındaki zararlı karışıklığı ölçülebilir biçimde azaltır; bu önemlidir
çünkü belge türü zorunlu alan kural tablosunu seçer.

Sinyaller modeli bilgilendirir; onu asla geçersiz kılmazlar. Gerçekten belirsiz
olan her şey sınıflandırıcının kararında kalır.
"""

import re

from pydantic import BaseModel, Field

# "T.C." aralarında boşluklu olabilir veya tam ifade yazılı olabilir.
TC_HEADER_PATTERN = re.compile(
    r"(^|\n)\s*(T\s*\.?\s*C\s*\.?|TÜRKİYE CUMHURİYETİ)\s*($|\n)", re.IGNORECASE
)
# Cümle ortasında geçen kelimenin aksine bir "Sayı" yan başlığı.
SAYI_FIELD_PATTERN = re.compile(r"(^|\n)\s*Sayı\s*:", re.IGNORECASE)
KONU_FIELD_PATTERN = re.compile(r"(^|\n)\s*Konu\s*:", re.IGNORECASE)
ILGI_FIELD_PATTERN = re.compile(r"(^|\n)\s*İlgi\s*:", re.IGNORECASE)
DISTRIBUTION_PATTERN = re.compile(r"DAĞITIM\s*(YERLERİNE)?", re.IGNORECASE)

# Bir imzanın altında görünen kurumsal unvanlar. Bir vatandaş dilekçesi bunları
# taşımaz. Yalnızca imza bloğu içinde eşleştirilir (bkz. SIGNATURE_BLOCK_LINES),
# çünkü aynı kelimeler bir dilekçenin muhatap satırında da geçer -- aksi halde
# "BELEDİYE BAŞKANLIĞINA" unvanlı bir imza olarak raporlanır ve sınıflandırıcıya
# sahte bir gözlem besler.
SIGNATURE_TITLE_PATTERN = re.compile(
    r"(Genel Müdür|Daire Başkanı|Şube Müdürü|Müdür|Vali|Kaymakam|Başkan|"
    r"Bakan|Bakan Yardımcısı|Rektör|Dekan|Müsteşar|Amir|Şef|Koordinatör)"
    # İmza yerine bir muhatabı işaretleyen yönelme/yön eklerini reddet
    # ("...BAŞKANLIĞINA", "...MÜDÜRLÜĞÜNE").
    r"(?!\w*(lığına|luguna|lığına|lüğüne|luğuna|liğine|na\b|ne\b))",
    re.IGNORECASE,
)
#: Kaç sondaki satırın imza bloğu sayılacağı.
SIGNATURE_BLOCK_LINES = 6
# Bir dilekçe için tipik olan, başvuranın kendi iletişim bloğu.
APPLICANT_CONTACT_PATTERN = re.compile(
    r"(^|\n)\s*(Adres|T\.?C\.? Kimlik No|TCKN|Telefon|E-?posta)\s*:", re.IGNORECASE
)


class StructuralSignal(BaseModel):
    """Gelen bir belgenin regex ile tespit edilen yapısal işaretleri."""

    has_institution_header: bool = Field(
        default=False, description="Belgede 'T.C.' kurum anteti var mı."
    )
    has_sayi_field: bool = Field(
        default=False, description="Belgede 'Sayı:' yan başlığı var mı."
    )
    has_konu_field: bool = Field(
        default=False, description="Belgede 'Konu:' yan başlığı var mı."
    )
    has_ilgi_field: bool = Field(
        default=False, description="Belgede 'İlgi:' yan başlığı var mı."
    )
    has_distribution: bool = Field(
        default=False, description="Belgede 'DAĞITIM' bölümü var mı."
    )
    has_titled_signature: bool = Field(
        default=False, description="İmza bölümünde kurumsal unvan var mı."
    )
    has_applicant_contact: bool = Field(
        default=False,
        description="Başvurana ait adres/iletişim bloğu var mı (dilekçe göstergesi).",
    )

    @property
    def looks_institutional(self) -> bool:
        """İşaretlerin bir kurum tarafından düzenlenen bir belgeye işaret edip etmediği."""
        return self.has_institution_header and (
            self.has_sayi_field or self.has_titled_signature
        )


def _signature_block(text: str) -> str:
    """İmzanın oturduğu, bir belgenin sondaki satırlarını döndürür.

    Args:
        text: Çıkarılan belge metni.

    Returns:
        Son boş olmayan satırlar, birleştirilmiş.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-SIGNATURE_BLOCK_LINES:])


def detect_structural_signal(text: str) -> StructuralSignal:
    """Bir belgenin metnindeki yapısal işaretleri tespit eder.

    Args:
        text: Çıkarılan belge metni.

    Returns:
        Tespit edilen sinyaller.
    """
    return StructuralSignal(
        has_institution_header=bool(TC_HEADER_PATTERN.search(text)),
        has_sayi_field=bool(SAYI_FIELD_PATTERN.search(text)),
        has_konu_field=bool(KONU_FIELD_PATTERN.search(text)),
        has_ilgi_field=bool(ILGI_FIELD_PATTERN.search(text)),
        has_distribution=bool(DISTRIBUTION_PATTERN.search(text)),
        has_titled_signature=bool(
            SIGNATURE_TITLE_PATTERN.search(_signature_block(text))
        ),
        has_applicant_contact=bool(APPLICANT_CONTACT_PATTERN.search(text)),
    )


def format_structural_signal(signal: StructuralSignal) -> str:
    """Sinyalleri bir prompt için kısa bir Türkçe gözlem bloğu olarak sunar.

    Args:
        signal: Tespit edilen sinyaller.

    Returns:
        Bir Türkçe gözlem bloğu, veya hiçbir şey tespit edilmediyse boş bir string.
    """
    observations = []
    if signal.has_institution_header:
        observations.append("kurum anteti ('T.C.') var")
    if signal.has_sayi_field:
        observations.append("'Sayı:' alanı var")
    if signal.has_ilgi_field:
        observations.append("'İlgi:' alanı var")
    if signal.has_distribution:
        observations.append("'DAĞITIM' bölümü var")
    if signal.has_titled_signature:
        observations.append("imza bölümünde kurumsal unvan var")
    if signal.has_applicant_contact:
        observations.append("başvurana ait adres/iletişim bloğu var")

    if not observations:
        return ""

    block = "\n\nBelge üzerinde tespit edilen biçimsel işaretler: " + ", ".join(
        observations
    ) + "."
    if signal.looks_institutional:
        block += (
            " Bu işaretler belgenin bir kurum tarafından düzenlendiğini gösterir; "
            "vatandaş başvurusu (petition / information_request) değildir."
        )
    return block
