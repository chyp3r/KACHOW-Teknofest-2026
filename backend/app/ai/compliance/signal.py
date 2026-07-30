"""Deterministic structural signals used to inform document-type classification.

An official institutional letter carries unmistakable structural markers -- the
"T.C." header, a "Sayı:" field, a titled signature block -- that are cheap to
detect with regular expressions and do not need model judgement. Feeding these as
factual observations into the classifier prompt measurably reduces the harmful
confusion between an institutional letter and a citizen petition, which matters
because the document type selects the required-field rule table.

The signals inform the model; they never override it. Anything genuinely
ambiguous stays the classifier's decision.
"""

import re

from pydantic import BaseModel, Field

# "T.C." possibly spaced or with the full phrase spelled out.
TC_HEADER_PATTERN = re.compile(
    r"(^|\n)\s*(T\s*\.?\s*C\s*\.?|TÜRKİYE CUMHURİYETİ)\s*($|\n)", re.IGNORECASE
)
# A "Sayı" side-heading, as opposed to the word appearing mid-sentence.
SAYI_FIELD_PATTERN = re.compile(r"(^|\n)\s*Sayı\s*:", re.IGNORECASE)
KONU_FIELD_PATTERN = re.compile(r"(^|\n)\s*Konu\s*:", re.IGNORECASE)
ILGI_FIELD_PATTERN = re.compile(r"(^|\n)\s*İlgi\s*:", re.IGNORECASE)
DISTRIBUTION_PATTERN = re.compile(r"DAĞITIM\s*(YERLERİNE)?", re.IGNORECASE)

# Institutional titles that appear under a signature. A citizen petition does not
# carry these. Matched only within the signature block (see SIGNATURE_BLOCK_LINES),
# because the same words occur in the addressee line of a petition -- "BELEDİYE
# BAŞKANLIĞINA" would otherwise be reported as a titled signature, feeding the
# classifier a false observation.
SIGNATURE_TITLE_PATTERN = re.compile(
    r"(Genel Müdür|Daire Başkanı|Şube Müdürü|Müdür|Vali|Kaymakam|Başkan|"
    r"Bakan|Bakan Yardımcısı|Rektör|Dekan|Müsteşar|Amir|Şef|Koordinatör)"
    # Reject the dative/directional suffixes that mark an addressee rather than a
    # signature ("...BAŞKANLIĞINA", "...MÜDÜRLÜĞÜNE").
    r"(?!\w*(lığına|luguna|lığına|lüğüne|luğuna|liğine|na\b|ne\b))",
    re.IGNORECASE,
)
#: How many trailing lines count as the signature block.
SIGNATURE_BLOCK_LINES = 6
# An applicant's own contact block, typical of a petition.
APPLICANT_CONTACT_PATTERN = re.compile(
    r"(^|\n)\s*(Adres|T\.?C\.? Kimlik No|TCKN|Telefon|E-?posta)\s*:", re.IGNORECASE
)


class StructuralSignal(BaseModel):
    """Regex-detected structural markers of an incoming document."""

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
        """Whether the markers point to a document issued by an institution."""
        return self.has_institution_header and (
            self.has_sayi_field or self.has_titled_signature
        )


def _signature_block(text: str) -> str:
    """Return the trailing lines of a document, where the signature sits.

    Args:
        text: The extracted document text.

    Returns:
        The last non-empty lines, joined.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-SIGNATURE_BLOCK_LINES:])


def detect_structural_signal(text: str) -> StructuralSignal:
    """Detect structural markers in a document's text.

    Args:
        text: The extracted document text.

    Returns:
        The detected signals.
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
    """Render the signals as a short Turkish observation block for a prompt.

    Args:
        signal: The detected signals.

    Returns:
        A Turkish observation block, or an empty string when nothing was detected.
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
