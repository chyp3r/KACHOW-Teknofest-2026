"""Resolve a free-text legislation citation to a (kanun, madde) pair.

Both `REQUIRED_FIELD_RULES` (`field_rule.py`) and the LLM's `mevzuat_references`
cite legislation as prose -- "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar
Hakkında Yönetmelik MADDE 15- (3)", "RYUEHY m.14", "Devlet Memurları Kanunu"
-- with no stable id anywhere. This module is the one place that turns such a
string into the two identifiers a knowledge-graph node needs.

`canonical_legislation` (`app.ai.verification.normalizers`) already does the
*canonicalisation* half -- "madde 11" / "m. 11" / "m.11" all fold to the same
"madde:11" -- but it matches a whole isolated span, not prose, and it keeps
law and article in separate namespaces on purpose (a draft citing article
4982 of *something* is not grounded by a source mentioning law 4982). A
knowledge graph needs the opposite: the join between them. `resolve_citation`
supplies that join, reusing `canonical_legislation` for the per-span
canonicalisation and `LEGISLATION_PATTERN` (`draft_verifier.py`) for finding
those spans inside prose -- its lookbehind guard against a document number's
tail ("E-22222222-903-118 sayılı yazınız") matters here too, since `ilgi`-
and `mevzuat`-style strings are full of document numbers.
"""

from dataclasses import dataclass
from typing import Optional

from app.ai.verification.draft_verifier import LEGISLATION_PATTERN
from app.ai.verification.normalizers import _fold, canonical_legislation

#: Duplicated from `app.ai.retrieval.mcp_mevzuat.CURATED_LEGISLATION` rather
#: than imported: that module pulls in langchain, BM25 and the MCP registry,
#: and its own docstring says "Never touches compliance." Duplication with a
#: sync test (see test_mevzuat_citation.py) is this repo's own established
#: answer to exactly this tradeoff -- `_LegislationRef`'s docstring documents
#: doing the same thing for the same reason, one level further out.
#:
#: The single source both `LAW_TITLES` (folded title -> number, for matching)
#: and `KANUN_TITLE` (number -> display title, for a graph node's label) are
#: derived from, so the title string itself is never written twice.
_CURATED_LAW: tuple[tuple[str, str], ...] = (
    ("2646", "Resmî Yazışmalarda Uygulanacak Usul ve Esaslar Hakkında Yönetmelik"),
    ("3071", "Dilekçe Hakkının Kullanılmasına Dair Kanun"),
    ("4982", "Bilgi Edinme Hakkı Kanunu"),
    ("657", "Devlet Memurları Kanunu"),
    ("6698", "Kişisel Verilerin Korunması Kanunu"),
    ("7201", "Tebligat Kanunu"),
    ("5070", "Elektronik İmza Kanunu"),
)

#: Folded title -> law number; a folded citation string is checked for
#: containing one of these as a substring, so `RYUEHY`'s title (no number in
#: it at all) resolves the same way a "3071 sayılı ..." title does.
LAW_TITLES: dict[str, str] = {_fold(title): number for number, title in _CURATED_LAW}

#: Law number -> display title, for labelling a Kanun graph node.
KANUN_TITLE: dict[str, str] = dict(_CURATED_LAW)

#: Abbreviations observed in real `mevzuat_references` output that don't
#: appear anywhere in the law's own title, so a title-substring match can
#: never catch them.
LAW_ALIASES: dict[str, str] = {
    _fold("RYUEHY"): "2646",
}


@dataclass(frozen=True)
class CitationRef:
    """The law number and article number resolved from one citation string.

    Both are plain identifiers (``"2646"``, ``"17"``), not the prefixed
    ``"kanun:2646"``/``"madde:17"`` form `canonical_legislation` returns --
    the knowledge-graph builder composes them together into a single node id
    (`madde:{kanun}:{madde}`), which needs the law number available as a
    plain value rather than re-parsed out of a prefixed string.
    """

    kanun: Optional[str]
    madde: Optional[str]


def _resolve_kanun(text: str, folded: str) -> Optional[str]:
    """Find the law number a citation refers to, trying the most explicit
    signal first: an actual "N sayılı" number in the text outranks a title
    match, which outranks an abbreviation."""
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("kanun:"):
            return canonical.removeprefix("kanun:")

    for title, number in LAW_TITLES.items():
        if title in folded:
            return number

    for alias, number in LAW_ALIASES.items():
        if alias in folded:
            return number

    return None


def _resolve_madde(text: str) -> Optional[str]:
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("madde:"):
            return canonical.removeprefix("madde:")
    return None


def resolve_citation(text: str) -> CitationRef:
    """Resolve a free-text legislation citation to a law and article number.

    Args:
        text: The citation as written, e.g. from `FieldRule.mevzuat` or an
            LLM-produced `mevzuat_references[].mevzuat` string.

    Returns:
        A `CitationRef` with either field `None` when that half of the
        citation could not be resolved -- never raises, since the source
        text is always either a hand-written constant (which the rule-table
        contract test in test_mevzuat_citation.py holds to full resolution)
        or unreliable model output (which is expected to sometimes fail).
    """
    folded = _fold(text)
    return CitationRef(kanun=_resolve_kanun(text, folded), madde=_resolve_madde(text))
