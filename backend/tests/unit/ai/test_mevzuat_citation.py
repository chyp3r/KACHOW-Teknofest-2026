"""Unit tests for resolving a free-text legislation citation to (kanun, madde).

Mock-free by design, same reasoning as test_field_parser.py: the resolver is a
pure string transform, so its result must be exactly reproducible.
"""

from app.ai.compliance.field_rule import LAW_3071, LAW_4982, RYUEHY, REQUIRED_FIELD_RULES
from app.ai.compliance.mevzuat_citation import LAW_TITLES, CitationRef, resolve_citation


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
