import logging
from typing import List

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.ai.agents.base import BaseAgent
from app.ai.embeddings.chunking.base import BaseChunker

logger = logging.getLogger(__name__)


class SemanticSection(BaseModel):
    """Anlamsal olarak tutarlı tek bir bölümü temsil eden Pydantic modeli."""

    title: str = Field(
        description="A descriptive title highlighting the core topic of this section."
    )
    summary: str = Field(
        description="A concise summary of the key facts and information in this section."
    )
    content: str = Field(
        description="The exact text from the original document that belongs to this section."
    )


class AgenticChunksResponse(BaseModel):
    """Bölümleri içeren yapılandırılmış agent yanıtı için Pydantic modeli."""

    sections: List[SemanticSection] = Field(
        description="List of semantically separated sections from the text."
    )


class AgenticChunker(BaseChunker):
    """Metni bağlamsal olarak dinamik biçimde bölümlere ayırmak için bir

    LLM/Agent kullanan ve her parça için zengin metadata (başlık, özet)
    üreten SOTA Agentic Chunker.
    """

    def __init__(self, agent: BaseAgent):
        """Agentic Chunker'ı başlatır.

        Args:
            agent: Anlamsal analiz ve yapılandırmayı gerçekleştirecek BaseAgent örneği.
        """
        self.agent = agent

    async def split_text(self, text: str, **kwargs) -> List[Document]:
        """Metni Agentic akıl yürütme ve yapılandırılmış çıkarım kullanarak böler."""
        if not text.strip():
            return []

        prompt = (
            "You are a professional document analysis agent. Your task is to analyze the provided text "
            "and segment it into logical, semantically coherent sections. For each section, you must:\n"
            "1. Extract the exact original text content.\n"
            "2. Generate a short, descriptive title.\n"
            "3. Generate a 1-2 sentence summary of the key information.\n\n"
            f"TEXT TO ANALYZE:\n\"\"\"\n{text}\n\"\"\""
        )

        try:
            # Agent'ın Pydantic doğrulama döngüsünü kullanarak yapılandırılmış yanıt üret
            response: AgenticChunksResponse = await self.agent.run_structured(
                messages=prompt, response_model=AgenticChunksResponse, **kwargs
            )

            documents = []
            for idx, sec in enumerate(response.sections):
                documents.append(
                    Document(
                        page_content=sec.content.strip(),
                        metadata={
                            "title": sec.title.strip(),
                            "summary": sec.summary.strip(),
                            "chunk_index": idx,
                            "method": "agentic",
                        },
                    )
                )
            return documents

        except Exception as e:
            logger.error(
                f"AgenticChunker failed: {e}. Falling back to paragraph split.",
                exc_info=True,
            )
            # Güvenli Yedek Plan: Çift yeni satırlara göre böl (paragraflar)
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            return [
                Document(
                    page_content=p,
                    metadata={
                        "chunk_index": idx,
                        "fallback": True,
                        "method": "paragraph_fallback",
                    },
                )
                for idx, p in enumerate(paragraphs)
            ]
