"""Unit tests for resolving a free-text legislation citation to (kanun, madde).

Mock-free by design, same reasoning as test_field_parser.py: the resolver is a
pure string transform, so its result must be exactly reproducible.
"""

from langchain_core.documents import Document

from app.ai.compliance.field_rule import LAW_3071, LAW_4982, RYUEHY, REQUIRED_FIELD_RULES
from app.ai.compliance.mevzuat_citation import (
    LAW_TITLES,
    CitationRef,
    citation_support,
    resolve_citation,
)


def test_title_only_citation_resolves_via_the_law_title():
    result = resolve_citation(f"{RYUEHY} m.11")
    assert result == CitationRef(kanun="2646", madde="11")


def test_number_prefixed_citation_resolves_via_the_law_number():
    result = resolve_citation(f"{LAW_3071} m.4")
    assert result == CitationRef(kanun="3071", madde="4")


def test_law_only_citation_with_no_article_resolves_kanun_and_leaves_madde_none():
    result = resolve_citation("Devlet Memurları Kanunu")
    assert result == CitationRef(kanun="657", madde=None)


def test_ryuehy_abbreviation_resolves_via_the_alias_table():
    result = resolve_citation("RYUEHY m.14")
    assert result == CitationRef(kanun="2646", madde="14")


def test_a_document_number_tail_is_never_mistaken_for_a_law_number():
    # Same lookbehind guard LEGISLATION_PATTERN documents for exactly this
    # shape -- "E-22222222-903-118 sayılı yazınız" must not yield law 118.
    result = resolve_citation("E-22222222-903-118 sayılı yazınız")
    assert result == CitationRef(kanun=None, madde=None)


def test_llm_style_citation_with_uppercase_madde_and_trailing_parenthetical():
    # Real observed form from mevzuat_references on the live corpus.
    result = resolve_citation(f"{RYUEHY} MADDE 15- (3)")
    assert result == CitationRef(kanun="2646", madde="15")


def test_llm_style_citation_with_no_article_number_at_all():
    # Real observed form: a section reference with no numeric madde.
    result = resolve_citation(f"{RYUEHY} - Tanımlar (Üstveri)")
    assert result == CitationRef(kanun="2646", madde=None)


def test_bilgi_edinme_citation_resolves_via_the_law_number():
    result = resolve_citation(f"{LAW_4982} m.6")
    assert result == CitationRef(kanun="4982", madde="6")


def test_every_rule_table_citation_resolves_to_both_kanun_and_madde():
    """The contract that makes the deterministic edge source *guaranteed*.

    If a future rule is added with a citation resolve_citation can't parse,
    the compliance-graph's rule edges silently lose that madde -- this test
    is the tripwire, not the golden-corpus test in knowledge_graph tests.
    """
    unresolved = []
    for document_type, rules in REQUIRED_FIELD_RULES.items():
        for rule in rules:
            result = resolve_citation(rule.mevzuat)
            if result.kanun is None or result.madde is None:
                unresolved.append((document_type, rule.key, rule.mevzuat, result))
    assert not unresolved, f"rule citations that failed to resolve fully: {unresolved}"


#: A realistic excerpt for RYUEHY madde 11, the shape `retrieve_mevzuat_node`
#: actually retrieves: page_content is the raw article text, metadata carries
#: the corpus's own title exactly as `_read_title` extracts it.
_RYUEHY_MADDE_11 = Document(
    page_content=(
        "MADDE 11- (1) Belgelerde sayı bulunması zorunludur. “Sayı:” "
        "sırasıyla; belgenin hazırlanma süreçlerini ifade eden elektronik "
        "ortam için “E” ibaresinden uygun olanı kullanır."
    ),
    metadata={"mevzuat": RYUEHY, "source": "resmi_yazisma_yonetmeligi.md"},
)
_RYUEHY_MADDE_12 = Document(
    page_content=(
        "MADDE 12- (1) Tarih; sayı ile aynı satırda olmak üzere yazı "
        "alanının en sağında gün, ay, yıl olarak rakamla yazılır."
    ),
    metadata={"mevzuat": RYUEHY, "source": "resmi_yazisma_yonetmeligi.md"},
)
_LAW_3071_EXCERPT = Document(
    page_content="MADDE 4- Dilekçede, dilekçe sahibinin adı, soyadı ve imzası bulunur.",
    metadata={"mevzuat": LAW_3071, "source": "dilekce_hakki_kanunu_3071.md"},
)


def test_citation_support_grounded_when_law_and_article_both_in_excerpts():
    support = citation_support(f"{RYUEHY} m.11", [_RYUEHY_MADDE_11])
    assert support == citation_support(f"{RYUEHY} m.11", [_RYUEHY_MADDE_11])
    assert support.law_supported is True
    assert support.article_supported is True
    assert support.grounded is True


def test_citation_support_scans_every_excerpt_not_just_the_first():
    # The cited article (12) lives in the second excerpt, not the first --
    # a naive "check only excerpts[0]" implementation would miss it.
    support = citation_support(f"{RYUEHY} m.12", [_RYUEHY_MADDE_11, _RYUEHY_MADDE_12])
    assert support.grounded is True


def test_citation_support_rejects_a_fabricated_article_under_a_real_law():
    # The law is genuinely among the excerpts; the article number is not --
    # this is the fabrication requirement 5 exists to catch.
    support = citation_support(f"{RYUEHY} m.99", [_RYUEHY_MADDE_11])
    assert support.law_supported is True
    assert support.article_supported is False
    assert support.grounded is False


def test_citation_support_rejects_a_law_absent_from_every_excerpt():
    support = citation_support(f"{LAW_3071} m.4", [_RYUEHY_MADDE_11])
    assert support.law_supported is False
    assert support.grounded is False


def test_citation_support_law_only_citation_is_grounded_without_an_article():
    # No article named -- nothing for article_supported to contradict.
    support = citation_support(RYUEHY, [_RYUEHY_MADDE_11])
    assert support.law_supported is True
    assert support.article_supported is True
    assert support.grounded is True


def test_citation_support_unresolvable_citation_is_never_grounded():
    # Names no checkable law or article at all -- must fail regardless of
    # what the excerpts contain, not vacuously pass like the law-only case.
    support = citation_support("Bilinmeyen bir hüküm uyarınca", [_RYUEHY_MADDE_11])
    assert support.law_supported is False
    assert support.article_supported is False
    assert support.grounded is False


def test_citation_support_with_no_excerpts_is_never_grounded():
    support = citation_support(f"{RYUEHY} m.11", [])
    assert support.grounded is False


def test_citation_support_distinguishes_two_different_laws_in_context():
    support = citation_support(f"{LAW_3071} m.4", [_RYUEHY_MADDE_11, _LAW_3071_EXCERPT])
    assert support.grounded is True


def test_law_titles_stays_in_sync_with_curated_legislation():
    """Guards LAW_TITLES against drifting from the registry it was copied from.

    Duplicated rather than imported: app.ai.retrieval.mcp_mevzuat pulls in
    langchain/BM25/MCP and its own docstring says "Never touches compliance."
    This test is imported only here, in the test file, never in production
    code -- so the module boundary stays real and drift still gets caught.
    """
    from app.ai.retrieval.mcp_mevzuat import CURATED_LEGISLATION
    from app.ai.verification.normalizers import _fold

    expected = {_fold(ref.title): ref.number for ref in CURATED_LEGISLATION}
    assert LAW_TITLES == expected
