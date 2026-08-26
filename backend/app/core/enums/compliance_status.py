from enum import StrEnum


class ComplianceStatus(StrEnum):
    """Gelen bir belgenin zorunlu alan kurallarına karşı kontrol edilmesinin sonucu.

    Bir model yargısından değil, eksik alanlar kümesinden deterministik olarak
    türetilir: hiçbir şey eksik değilse `COMPLIANT`, en az bir zorunlu alan
    yoksa `INCOMPLETE`, ve yalnızca tavsiye niteliğindeki alanlar eksikse
    `PARTIALLY_COMPLIANT`.
    """

    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    INCOMPLETE = "incomplete"
