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

`citation_support` is the second consumer of the same join, for a different
question: not "what does this citation refer to" but "is what it refers to
actually present in the excerpts the model was given". This is what
`suggest_mevzuat_node` (`document_analysis_graph.py`) checks a suggestion
against before it reaches the API response -- the excerpts are the only
legislation text the model saw, so a citation naming a law or article absent
from all of them was not read off the retrieved text at all.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from langchain_core.documents import Document

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


def _resolve_all_madde(text: str) -> set[str]:
    """Collect every article number mentioned anywhere in a longer passage.

    `_resolve_madde` deliberately stops at the first match -- right for a
    short one-citation string, wrong for a whole excerpt, which typically
    spans several consecutive articles. `citation_support` needs every one
    an excerpt mentions, not just the first.
    """
    found: set[str] = set()
    for match in LEGISLATION_PATTERN.finditer(text):
        canonical = canonical_legislation(match.group(0))
        if canonical and canonical.startswith("madde:"):
            found.add(canonical.removeprefix("madde:"))
    return found


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


@dataclass(frozen=True)
class CitationSupport:
    """Whether a citation's law and article are actually present in a set of
    retrieved legislation excerpts.

    ``article_supported`` is vacuously ``True`` when the citation names no
    article at all -- a law-only citation ("Devlet Memurları Kanunu") makes no
    article-level claim for the excerpts to fail, so there is nothing to
    contradict. Callers that only need the combined verdict should use
    `grounded`, not either flag alone.
    """

    law_supported: bool
    article_supported: bool

    @property
    def grounded(self) -> bool:
        """The single pass/fail verdict: both halves of the citation hold."""
        return self.law_supported and self.article_supported


def citation_support(citation: str, excerpts: Sequence[Document]) -> CitationSupport:
    """Check a legislation citation against the excerpts it was supposedly drawn from.

    Resolves the citation the same way `resolve_citation` resolves any other
    citation string. Resolves each excerpt independently: its law from
    `metadata["mevzuat"]` (the corpus's own title, via the same title/alias
    matching `_resolve_kanun` already does for prose) and *every* article
    number mentioned anywhere in its `page_content` (`_resolve_all_madde` --
    an excerpt chunk commonly spans several consecutive articles, unlike a
    short citation string).

    Args:
        citation: A `mevzuat_references[].mevzuat`-style citation string.
        excerpts: The legislation passages retrieved for this document --
            the only source the citation could legitimately have come from.

    Returns:
        `CitationSupport` reporting whether the citation's law and article
        are each backed by at least one excerpt. A citation that resolves to
        neither a law nor an article (`resolve_citation` found nothing
        checkable) is reported as wholly unsupported regardless of the
        excerpts -- it names no authority to verify against.
    """
    ref = resolve_citation(citation)
    if ref.kanun is None and ref.madde is None:
        return CitationSupport(law_supported=False, article_supported=False)

    excerpt_refs = [
        (_resolve_kanun(document.metadata.get("mevzuat", ""), _fold(document.metadata.get("mevzuat", ""))),
         _resolve_all_madde(document.page_content))
        for document in excerpts
    ]

    law_supported = ref.kanun is not None and any(
        excerpt_kanun == ref.kanun for excerpt_kanun, _ in excerpt_refs
    )
    if ref.madde is None:
        article_supported = True
    else:
        article_supported = any(
            excerpt_kanun == ref.kanun and ref.madde in excerpt_maddeler
            for excerpt_kanun, excerpt_maddeler in excerpt_refs
        )

    return CitationSupport(law_supported=law_supported, article_supported=article_supported)
