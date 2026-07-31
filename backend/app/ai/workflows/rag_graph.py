import logging
from typing import Any, Dict, List, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.base import BaseAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)


class RAGState(TypedDict):
    """LangGraph State representing the RAG (retrieval) workflow context."""

    original_query: str
    rewritten_query: str
    documents: List[Document]
    context: str
    attempts: int


class QueryRewriteOutput(BaseModel):
    """Pydantic schema for structured query rewriting."""

    rewritten_query: str = Field(
        description="Arama doğruluğunu artırmak için zenginleştirilmiş/düzeltilmiş Türkçe sorgu."
    )


def create_rag_graph(
    llm_client: BaseLLMClient, hybrid_retriever: HybridRetriever
):
    """Create and compile the LangGraph RAG workflow with query rewriting,

    and parallel hybrid retrieval.

    Flow: START -> Rewrite Query -> Retrieve Docs -> END
    """
    rewriter_agent = BaseAgent(
        llm_client=llm_client,
        name="QueryRewriter",
        description="Rewrites queries to improve search recall.",
        system_prompt=(
            "Sen bir arama sorgusu zenginleştirme asistanısın. Görevin, verilen sorguyu arama motorlarında "
            "en iyi sonuçları getirecek şekilde Türkçe olarak zenginleştirmektir. "
            "ÖNEMLİ KURALLAR: "
            "1. Çıktıyı belirtilen JSON şemasında ver. "
            "2. JSON anahtar (key) isimlerini KESİNLİKLE Türkçe'ye çevirme. Yalnızca 'rewritten_query' anahtarını kullan."
        )
    )

    # 1. Query Rewrite Node
    async def rewrite_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Query Rewrite Node...")
        attempts = state.get("attempts", 0)

        prompt = (
            f"Sorgu: \"{state['original_query']}\"\n"
            "Bu sorguyu arama motorunda (vektör/keyword) en iyi sonuçları getirecek şekilde, "
            "anlamsal olarak zenginleştirerek genişletilmiş bir Türkçe arama sorgusu haline getir."
        )

        try:
            res: QueryRewriteOutput = await rewriter_agent.run_structured(
                messages=prompt, response_model=QueryRewriteOutput
            )
            return {"rewritten_query": res.rewritten_query, "attempts": attempts + 1}
        except Exception as e:
            logger.error(f"Query Rewrite Node failed: {e}", exc_info=True)
            return {"rewritten_query": state["original_query"], "attempts": attempts + 1}

    # 2. Retrieve Node
    async def retrieve_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Retrieve Node...")
        query_to_search = state.get("rewritten_query") or state["original_query"]
        try:
            # Query Hybrid Retriever (Dense + BM25 parallel + RRF)
            docs = await hybrid_retriever.retrieve(query_to_search, limit=4)
            context_str = "\n\n".join(
                [f"[DOKÜMAN {idx}]:\n{doc.page_content}" for idx, doc in enumerate(docs)]
            )
            return {"documents": docs, "context": context_str}
        except Exception as e:
            logger.error(f"Retrieve Node failed: {e}", exc_info=True)
            return {"documents": [], "context": ""}

    # Define Graph
    builder = StateGraph(RAGState)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("retrieve", retrieve_node)

    builder.add_edge(START, "rewrite")
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("retrieve", END)

    return builder.compile()
