import logging
import re
from typing import Any, Dict, List, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)

RETRIEVAL_LIMIT = 4

#: Words that carry no retrieval signal but dominate a naive query. Removing
#: them lets the BM25 half of the hybrid retriever score on the terms that
#: actually appear in the regulation.
TURKISH_STOPWORDS = frozenset(
    {
        "acaba", "ama", "ancak", "bana", "bazı", "belki", "ben", "beni", "benim",
        "bir", "biri", "birkaç", "birşey", "biz", "bu", "buna", "bunu", "bunun",
        "çok", "çünkü", "da", "daha", "de", "değil", "diye", "eğer", "en", "gibi",
        "hem", "hep", "hepsi", "her", "hiç", "için", "ile", "ise", "kez", "ki",
        "kim", "mi", "mı", "mu", "mü", "nasıl", "ne", "neden", "nerde", "nerede",
        "nereye", "niçin", "niye", "o", "sanki", "şey", "siz", "şu", "tüm", "ve",
        "veya", "ya", "yani", "olarak", "olan", "bunlar", "hakkında", "kadar",
        "sonra", "önce", "üzere", "göre",
    }
)

#: Terms worth appending to a bare question so the sparse retriever has literal
#: regulation vocabulary to match on.
DOMAIN_EXPANSION = "mevzuat yönetmelik madde hüküm resmî yazışma"


class RAGState(TypedDict, total=False):
    """LangGraph state for the retrieval workflow."""

    original_query: str
    search_query: str
    documents: List[Document]
    context: str
    attempts: int


def build_search_query(query: str) -> str:
    """Turn a user question into a retrieval query without calling a model.

    The analysis graph already established (see ``_build_mevzuat_query``) that
    deterministic query construction beats a model rewrite against this corpus,
    because the retriever's sparse half matches literal regulation tokens. The
    rewrite node this replaces spent a full generation to reach a worse query.

    Args:
        query: The user's question or the document summary.

    Returns:
        A keyword-dense query string.
    """
    cleaned = re.sub(r"[^\w\sçğıöşüÇĞİÖŞÜ]", " ", query or "").strip()
    if not cleaned:
        return ""

    terms = [
        token
        for token in cleaned.split()
        if len(token) > 2 and token.lower() not in TURKISH_STOPWORDS
    ]
    if not terms:
        terms = cleaned.split()

    # Keep the query bounded: past roughly a dozen terms BM25 scoring flattens
    # out and the dense half starts averaging unrelated topics together.
    return " ".join(terms[:12] + [DOMAIN_EXPANSION])


def create_rag_graph(llm_client: BaseLLMClient, hybrid_retriever: HybridRetriever):
    """Create and compile the retrieval workflow.

    Flow: START -> prepare_query -> retrieve -> END

    Args:
        llm_client: Retained for interface compatibility; retrieval no longer
            needs a model.
        hybrid_retriever: Dense + sparse retriever over the legislation corpus.

    Returns:
        The compiled LangGraph workflow.
    """

    async def prepare_query_node(state: RAGState) -> Dict[str, Any]:
        query = build_search_query(state.get("original_query", ""))
        logger.info("Prepared retrieval query: %s", query)
        return {"search_query": query, "attempts": state.get("attempts", 0) + 1}

    async def retrieve_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Retrieve Node...")
        query = state.get("search_query") or state.get("original_query", "")
        try:
            docs = await hybrid_retriever.retrieve(query, limit=RETRIEVAL_LIMIT)
            context = "\n\n".join(
                f"[DOKÜMAN {index}] (Kaynak: {doc.metadata.get('mevzuat', 'bilinmiyor')})\n"
                f"{doc.page_content}"
                for index, doc in enumerate(docs, start=1)
            )
            return {"documents": docs, "context": context}
        except Exception:
            logger.exception("Retrieve Node failed")
            return {"documents": [], "context": ""}

    builder = StateGraph(RAGState)
    builder.add_node("prepare_query", prepare_query_node)
    builder.add_node("retrieve", retrieve_node)

    builder.add_edge(START, "prepare_query")
    builder.add_edge("prepare_query", "retrieve")
    builder.add_edge("retrieve", END)

    return builder.compile()
