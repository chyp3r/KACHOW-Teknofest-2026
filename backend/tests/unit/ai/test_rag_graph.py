"""Unit tests for the legislation retrieval sub-graph.

build_search_query() is deterministic (no model rewrite call) on the same
grounds as document_analysis_graph._build_mevzuat_query: the sparse half of
the hybrid retriever matches literal regulation tokens, so a keyword-dense
query beats a paraphrased one.
"""

from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document

from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.rag_graph import (
    DOMAIN_EXPANSION,
    TURKISH_STOPWORDS,
    _turkish_lower,
    build_search_query,
    create_rag_graph,
)


def test_turkish_lower_folds_the_dotted_capital_i_python_gets_wrong():
    assert _turkish_lower("İçin") == "için"
    assert _turkish_lower("İLE") == "ile"
    assert _turkish_lower("İçin") in TURKISH_STOPWORDS


def test_turkish_lower_leaves_plain_ascii_untouched():
    """The fix is scoped to the one codepoint Python's .lower() gets wrong --
    not a general Turkish-locale casing change."""
    assert _turkish_lower("IZIN") == "izin"


def test_build_search_query_is_deterministic():
    query = "İzin talebi nasıl yapılır?"
    assert build_search_query(query) == build_search_query(query)


def test_build_search_query_strips_stopwords():
    query = build_search_query("Bu evrak için ne yapmalıyım ve nereye başvurmalıyım")
    assert "bu" not in query.split()
    assert "icin" not in query.lower()
    # A content word from the same sentence must survive.
    assert "başvurmalıyım" in query or "evrak" in query


def test_build_search_query_strips_capitalised_stopwords_too():
    """Regression: `token.lower()` maps 'İ' (U+0130, dotted capital I) to a
    two-codepoint 'i' + combining dot (U+0307), which never equals the plain
    single-codepoint 'için' the stopword set is written with -- so a query
    capitalising the word (sentence-initial, as in real usage) let it survive
    filtering and consume one of the 12-term budget as a content word BM25
    would then score on."""
    query = build_search_query("İzin talebi İçin hangi belgeler gerekli?")
    terms = query.split()[:-len(DOMAIN_EXPANSION.split())]
    assert "İçin" not in terms
    assert "için" not in terms
    # A genuine content word from the same sentence, unaffected by the fix,
    # must still survive -- this isn't a test of over-aggressive filtering.
    assert "İzin" in terms


def test_build_search_query_falls_back_to_raw_terms_when_everything_is_a_stopword():
    """A query made entirely of stopwords/short tokens must not collapse to
    an empty search -- the raw tokens are still better than nothing."""
    query = build_search_query("bu ve şu ile")
    assert query != DOMAIN_EXPANSION.strip()
    for token in ("bu", "ve", "şu", "ile"):
        assert token in query


def test_build_search_query_caps_at_twelve_terms_plus_domain_expansion():
    many_terms = " ".join(f"terim{i}" for i in range(30))
    query = build_search_query(many_terms)

    domain_terms = DOMAIN_EXPANSION.split()
    kept = query.split()[: -len(domain_terms)]
    assert len(kept) == 12
    assert query.endswith(DOMAIN_EXPANSION)


def test_build_search_query_appends_domain_expansion_terms():
    query = build_search_query("izin talebi")
    for term in DOMAIN_EXPANSION.split():
        assert term in query


def test_build_search_query_handles_empty_input():
    assert build_search_query("") == ""
    assert build_search_query(None) == ""


def test_build_search_query_strips_punctuation():
    query = build_search_query("İzin talebi, nasıl (yapılır)?!")
    assert "," not in query
    assert "(" not in query
    assert "?" not in query


@pytest.mark.asyncio
async def test_graph_uses_the_prepared_query_and_returns_rendered_context():
    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = [
        Document(page_content="MADDE 5- ...", metadata={"mevzuat": "Yönetmelik"})
    ]
    graph = create_rag_graph(llm_client=None, hybrid_retriever=retriever)

    result = await graph.ainvoke({"original_query": "izin talebi"})

    assert len(result["documents"]) == 1
    assert "[DOKÜMAN 1]" in result["context"]
    assert "Yönetmelik" in result["context"]
    called_query = retriever.retrieve.await_args.args[0]
    assert called_query == build_search_query("izin talebi")


@pytest.mark.asyncio
async def test_graph_degrades_to_empty_results_on_retriever_failure():
    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.side_effect = Exception("Qdrant down")
    graph = create_rag_graph(llm_client=None, hybrid_retriever=retriever)

    result = await graph.ainvoke({"original_query": "izin talebi"})

    assert result["documents"] == []
    assert result["context"] == ""


@pytest.mark.asyncio
async def test_graph_tracks_attempts_across_invocations_of_the_same_state():
    retriever = AsyncMock(spec=HybridRetriever)
    retriever.retrieve.return_value = []
    graph = create_rag_graph(llm_client=None, hybrid_retriever=retriever)

    result = await graph.ainvoke({"original_query": "x", "attempts": 2})

    assert result["attempts"] == 3
