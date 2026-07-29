import logging
from typing import Any, List

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.ai.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class DocumentRelevance(BaseModel):
    """Pydantic model representing the relevance score of a single document."""

    index: int = Field(
        description="Dokümanın listedeki sıfır tabanlı (0-based) indeks numarası."
    )
    relevance_score: float = Field(
        description="Dokümanın sorgu ile olan alaka düzeyi (0.0 ile 10.0 arasında)."
    )
    reason: str = Field(
        description="Bu alaka puanının atanmasındaki ana gerekçe."
    )


class RerankResponse(BaseModel):
    """Pydantic model containing the complete list of document relevance scores."""

    scores: List[DocumentRelevance] = Field(
        description="Değerlendirilen tüm dokümanlar için atanan alaka skorları."
    )


class LLMReranker:
    """SOTA Reranker that uses a BaseAgent to perform structured evaluation and scoring

    of retrieved documents based on their semantic relevance to the query.
    """

    def __init__(self, agent: BaseAgent):
        """Initialize LLM Reranker.

        Args:
            agent: An instance of BaseAgent to evaluate document relevance.
        """
        self.agent = agent
        logger.info("Initialized LLMReranker.")

    async def rerank(
        self, query: str, documents: List[Document]
    ) -> List[Document]:
        """Evaluate, score, and sort documents by their semantic relevance to the query.

        Args:
            query: The user search query.
            documents: List of retrieved Document candidates.
        """
        if not documents or not query.strip():
            return documents

        # Build prompt listing all candidate documents
        doc_list_str = ""
        for idx, doc in enumerate(documents):
            doc_list_str += (
                f"[DOKÜMAN İNDEKSİ: {idx}]\n"
                f"İçerik: \"\"\"\n{doc.page_content}\n\"\"\"\n\n"
            )

        prompt = (
            "Sen bir bilgi erişimi ve alaka düzeyi denetleme uzmanısın. Görevin, verilen sorgu ile "
            "aşağıdaki dokümanları teker teker karşılaştırmak ve her biri için sorguyla olan alaka düzeyini "
            "0.0 (tamamen alakasız) ile 10.0 (tamamen alakalı/birebir cevap) arasında puanlamaktır.\n\n"
            f"KULLANICI SORGUSU: \"{query}\"\n\n"
            f"DEĞERLENDİRİLECEK DOKÜMANLAR:\n{doc_list_str}"
            "Lütfen her bir doküman için listedeki indeks numarasını koruyarak alaka puanı (relevance_score) "
            "ve kısa gerekçesini (reason) Türkçe olarak yapılandırılmış formatta döndür."
        )

        try:
            # Perform structured LLM call
            result: RerankResponse = await self.agent.run_structured(
                messages=prompt, response_model=RerankResponse
            )

            # Map scores back to documents
            scored_docs = []
            score_map = {item.index: item for item in result.scores}

            for idx, doc in enumerate(documents):
                new_doc = Document(
                    page_content=doc.page_content, metadata=doc.metadata.copy()
                )

                # Retrieve LLM score if available, otherwise default to 0.0
                rel_item = score_map.get(idx)
                if rel_item:
                    new_doc.metadata["relevance_score"] = float(
                        rel_item.relevance_score
                    )
                    new_doc.metadata["rerank_reason"] = rel_item.reason
                else:
                    new_doc.metadata["relevance_score"] = 0.0

                scored_docs.append(new_doc)

            # Sort documents by relevance score descending
            sorted_docs = sorted(
                scored_docs,
                key=lambda x: x.metadata.get("relevance_score", 0.0),
                reverse=True,
            )

            logger.info(
                f"LLMReranker successfully re-ranked {len(sorted_docs)} documents."
            )
            return sorted_docs

        except Exception as e:
            logger.error(
                f"LLMReranker failed, falling back to original document order: {e}",
                exc_info=True,
            )
            # Safe Fallback: Return original documents list untouched
            return documents
