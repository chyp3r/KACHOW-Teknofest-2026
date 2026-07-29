import logging
from typing import Any, Dict, List, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.agents.verifier import VerifierAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever

logger = logging.getLogger(__name__)


class RAGState(TypedDict):
    """LangGraph State representing the RAG (retrieval & validation) workflow context."""

    original_query: str
    rewritten_query: str
    documents: List[Document]
    context: str
    verification_status: str  # "SUFFICIENT" or "INSUFFICIENT"
    verifier_feedback: str
    attempts: int


class QueryRewriteOutput(BaseModel):
    """Pydantic schema for structured query rewriting."""

    rewritten_query: str = Field(
        description="Arama doğruluğunu artırmak için zenginleştirilmiş/düzeltilmiş Türkçe sorgu."
    )


class VerifierOutput(BaseModel):
    """Pydantic schema for context verification."""

    status: str = Field(
        description="Sorguyu cevaplamak için bağlam yeterliliği. 'SUFFICIENT' (Yeterli) veya 'INSUFFICIENT' (Yetersiz) olmalıdır."
    )
    feedback: str = Field(
        description="Eğer bağlam yetersizse eksik kalan noktalar, yeterliyse kısa gerekçe."
    )


def create_rag_graph(
    llm_client: BaseLLMClient, hybrid_retriever: HybridRetriever
):
    """Create and compile the LangGraph RAG workflow with query rewriting,

    parallel hybrid retrieval, and verifier loop.

    Flow: START -> Rewrite Query -> Retrieve Docs -> Verify Context -> (Sufficient? END : Loop Rewrite)
    """
    # Instantiate verifier agent
    verifier_agent = VerifierAgent(llm_client)

    # 1. Query Rewrite Node
    async def rewrite_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Query Rewrite Node...")
        attempts = state.get("attempts", 0)
        feedback = state.get("verifier_feedback", "")

        # If it's a retry, inject feedback to LLM to guide rewriting
        if attempts > 0 and feedback:
            prompt = (
                f"Sorgu: \"{state['original_query']}\"\n"
                f"Önceki arama başarısız oldu çünkü veritabanı doğrulaması şu geribildirimi verdi: \"{feedback}\"\n"
                "Lütfen bu geribildirimi göz önüne alarak, veritabanından eksik olan bu bilgileri "
                "yakalayabilecek daha detaylı ve alternatif terimler içeren yeni bir Türkçe arama sorgusu yaz."
            )
        else:
            prompt = (
                f"Sorgu: \"{state['original_query']}\"\n"
                "Bu sorguyu arama motorunda (vektör/keyword) en iyi sonuçları getirecek şekilde, "
                "anlamsal olarak zenginleştirerek genişletilmiş bir Türkçe arama sorgusu haline getir."
            )

        try:
            res: QueryRewriteOutput = await verifier_agent.run_structured(
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

    # 3. Verify Node
    async def verify_node(state: RAGState) -> Dict[str, Any]:
        logger.info("Running Verify Node...")
        if not state["documents"]:
            return {
                "verification_status": "INSUFFICIENT",
                "verifier_feedback": "Hiçbir doküman bulunamadı.",
            }

        prompt = (
            f"Kullanıcı Sorgusu: \"{state['original_query']}\"\n\n"
            f"Elde Edilen Bağlam:\n\"\"\"\n{state['context']}\n\"\"\"\n\n"
            "Bu bağlam, kullanıcının sorusunu eksiksiz ve doğru bir şekilde cevaplamak için yeterli mi? "
            "Lütfen bunu değerlendir ve yapılandırılmış formatta durum ile gerekçe/geribildirim döndür."
        )

        try:
            res: VerifierOutput = await verifier_agent.run_structured(
                messages=prompt, response_model=VerifierOutput
            )
            return {
                "verification_status": res.status.upper(),
                "verifier_feedback": res.feedback,
            }
        except Exception as e:
            logger.error(f"Verify Node failed: {e}", exc_info=True)
            return {
                "verification_status": "SUFFICIENT",
                "verifier_feedback": "Doğrulama hatası oluştu, devam ediliyor.",
            }

    # Conditional Routing Logic
    def route_after_verify(state: RAGState) -> str:
        status = state.get("verification_status", "SUFFICIENT")
        attempts = state.get("attempts", 0)

        # If sufficient or we hit maximum limit (e.g. 2 attempts), end RAG
        if status == "SUFFICIENT" or attempts >= 2:
            logger.info("RAG verification SUFFICIENT or maximum attempts hit. Routing to END.")
            return "end"
        
        logger.warning(
            f"RAG verification INSUFFICIENT (Attempt {attempts}). Feedback: {state.get('verifier_feedback')}. Retrying rewrite..."
        )
        return "rewrite"

    # Define Graph
    builder = StateGraph(RAGState)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("verify", verify_node)

    builder.add_edge(START, "rewrite")
    builder.add_edge("rewrite", "retrieve")
    builder.add_edge("retrieve", "verify")

    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {
            "end": END,
            "rewrite": "rewrite",
        },
    )

    return builder.compile()
