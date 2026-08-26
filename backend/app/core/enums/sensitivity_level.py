from enum import StrEnum


class SensitivityLevel(StrEnum):
    """Resmi Türkçe belge gizlilik dereceleri (``gizlilik derecesi``).

    Çağıranların seviyeleri doğrudan karşılaştırabilmesi için en az
    kısıtlayıcıdan en çok kısıtlayıcıya sıralanmıştır
    (``level >= SensitivityLevel.GIZLI``). ``UNMARKED``, ``TASNIF_DISI``'nin
    (açık "tasnif dışı" derecesi) altında yer alır -- hiç derece
    belirtmeyen bir belge, olumlu olarak tasnif dışı işaretlenmiş bir
    belgeyle aynı gerçek değildir, ama ikisi de kendi başına hiçbir şeyi
    engellemez.

    ``rank``, bir int ile aynı sıralamadır, çünkü Qdrant payload
    filtreleri enum üyelerini değil sayıları karşılaştırır: parça/belge
    metadatası tam olarak bu nedenle bu değerin dizesiyle birlikte
    ``sensitivity_rank``'i saklar (bkz. ``app.ai.retrieval`` aralık-filtre
    bağlantısı).
    """

    UNMARKED = "unmarked"
    TASNIF_DISI = "tasnif_disi"
    HIZMETE_OZEL = "hizmete_ozel"
    OZEL = "ozel"
    GIZLI = "gizli"
    COK_GIZLI = "cok_gizli"

    @property
    def rank(self) -> int:
        """Bu seviyenin sıralamadaki konumu, en düşükten en yükseğe."""
        return _RANK[self]

    def __ge__(self, other: "SensitivityLevel") -> bool:
        return self.rank >= other.rank

    def __gt__(self, other: "SensitivityLevel") -> bool:
        return self.rank > other.rank

    def __le__(self, other: "SensitivityLevel") -> bool:
        return self.rank <= other.rank

    def __lt__(self, other: "SensitivityLevel") -> bool:
        return self.rank < other.rank


_RANK: dict[SensitivityLevel, int] = {
    SensitivityLevel.UNMARKED: 0,
    SensitivityLevel.TASNIF_DISI: 1,
    SensitivityLevel.HIZMETE_OZEL: 2,
    SensitivityLevel.OZEL: 3,
    SensitivityLevel.GIZLI: 4,
    SensitivityLevel.COK_GIZLI: 5,
}

#: Türkçe etiket varyantları -> kanonik seviye, aksan-katlanmış, küçük
#: harfli metne karşı eşleştirilir (bkz.
#: ``app.ai.guardrails.sensitivity._fold``). Bir belgenin serbest metin
#: ``gizlilik_derecesi`` değerleri nadiren tek bir yazımla eşleşir.
LABEL_ALIASES: dict[str, SensitivityLevel] = {
    "tasnif disi": SensitivityLevel.TASNIF_DISI,
    "tasnifdisi": SensitivityLevel.TASNIF_DISI,
    "hizmete ozel": SensitivityLevel.HIZMETE_OZEL,
    "ozel": SensitivityLevel.OZEL,
    "gizli": SensitivityLevel.GIZLI,
    "cok gizli": SensitivityLevel.COK_GIZLI,
    "çok gizli": SensitivityLevel.COK_GIZLI,
}
