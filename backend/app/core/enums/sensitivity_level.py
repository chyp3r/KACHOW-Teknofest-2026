from enum import StrEnum


class SensitivityLevel(StrEnum):
    """Official Turkish document confidentiality grades (``gizlilik derecesi``).

    Ordered from least to most restrictive so callers can compare levels
    directly (``level >= SensitivityLevel.GIZLI``). ``UNMARKED`` sits below
    ``TASNIF_DISI`` (the explicit "unclassified" grade) -- a document that
    never stated a grade at all is not the same fact as one that was
    positively marked unclassified, but neither blocks anything on its own.

    ``rank`` is the same ordering as an int, because Qdrant payload filters
    compare numbers, not enum members: chunk/document metadata stores
    ``sensitivity_rank`` alongside this value's string for exactly that
    reason (see ``app.ai.retrieval`` range-filter wiring).
    """

    UNMARKED = "unmarked"
    TASNIF_DISI = "tasnif_disi"
    HIZMETE_OZEL = "hizmete_ozel"
    OZEL = "ozel"
    GIZLI = "gizli"
    COK_GIZLI = "cok_gizli"

    @property
    def rank(self) -> int:
        """This level's position in the ordering, lowest to highest."""
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

#: Turkish label variants -> canonical level, matched against diacritic-folded,
#: lowercased text (see ``app.ai.guardrails.sensitivity._fold``). Free-text
#: ``gizlilik_derecesi`` values from a document rarely match one spelling.
LABEL_ALIASES: dict[str, SensitivityLevel] = {
    "tasnif disi": SensitivityLevel.TASNIF_DISI,
    "tasnifdisi": SensitivityLevel.TASNIF_DISI,
    "hizmete ozel": SensitivityLevel.HIZMETE_OZEL,
    "ozel": SensitivityLevel.OZEL,
    "gizli": SensitivityLevel.GIZLI,
    "cok gizli": SensitivityLevel.COK_GIZLI,
    "çok gizli": SensitivityLevel.COK_GIZLI,
}
