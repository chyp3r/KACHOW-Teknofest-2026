import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from app.ai.agents.base import BaseAgent
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.embeddings.service import EmbeddedChunk
from app.infrastructure.vectorstore.base import BaseVectorStore

logger = logging.getLogger(__name__)


class MemoryFact(BaseModel):
    """Pydantic schema representing the list of extracted preferences and facts."""

    facts: List[str] = Field(
        description="Metinden çıkarılan kullanıcı tercihleri, ilgileri, projeleri ve kendisiyle ilgili olguların listesi."
    )


class VectorMemory:
    """SOTA Semantic/Episodic Memory client (Custom Mem0) that extracts, stores,

    and retrieves user preferences and facts from conversation history using Qdrant.
    """

    def __init__(
        self,
        vector_store: BaseVectorStore,
        embeddings_client: BaseEmbeddingsClient,
        agent: BaseAgent,
        collection_name: str = "user_episodic_memory",
    ):
        """Initialize Vector/Episodic Memory.

        Args:
            vector_store: BaseVectorStore (e.g. QdrantStore) client.
            embeddings_client: BaseEmbeddingsClient to vectorise the facts.
            agent: BaseAgent (or custom agent) to extract the facts.
            collection_name: The name of the collection in vector database.
        """
        self.vector_store = vector_store
        self.embeddings_client = embeddings_client
        self.agent = agent
        self.collection_name = collection_name
        self._collection_created = False
        logger.info(
            f"Initialized VectorMemory (Mem0-like) targeting collection: {collection_name}"
        )

    async def _ensure_collection(self) -> None:
        """Helper to dynamically fetch embedding size and create collection in vector DB."""
        if not self._collection_created:
            # Query a dummy string to detect embedding dimensions dynamically
            dummy_vec = await self.embeddings_client.embed_query("dummy")
            vector_size = len(dummy_vec)
            logger.info(
                f"VectorMemory detected embedding dimension size: {vector_size}. Creating collection..."
            )
            await self.vector_store.create_collection(
                collection_name=self.collection_name, vector_size=vector_size
            )
            self._collection_created = True

    async def add_conversation_turn(
        self, session_id: str, user_message: str, assistant_message: str
    ) -> List[str]:
        """Analyze a conversation turn, extract facts using the agent, and save to vector DB.

        Args:
            session_id: Unique chat session ID.
            user_message: User input message.
            assistant_message: Assistant response message.

        Returns:
            A list of extracted facts strings.
        """
        await self._ensure_collection()

        prompt = (
            "Sen bir kullanıcı hafıza analizi ajanısın. Görevin, aşağıdaki konuşma adımını incelemek "
            "ve kullanıcının kendisi hakkında doğrudan veya dolaylı olarak belirttiği olguları, "
            "tercihleri, mesleğini, ilgi alanlarını ve projelerini Türkçe olarak maddeler halinde çıkarmaktır.\n\n"
            f"KULLANICI: \"{user_message}\"\n"
            f"ASİSTAN: \"{assistant_message}\"\n\n"
            "Önemli Yönergeler:\n"
            "- Çıkarımların kısa, net ve üçüncü şahıs gözünden olmalıdır (örn. 'Kullanıcı Python programlama dili biliyor').\n"
            "- Sadece yeni, somut ve kalıcı bilgi değeri olan olguları çıkar.\n"
            "- Eğer konuşmada yeni bir olgu veya kişisel bilgi yoksa boş liste döndür."
        )

        try:
            # Use SOTA run_structured pydantic loop to get structured facts list
            result: MemoryFact = await self.agent.run_structured(
                messages=prompt, response_model=MemoryFact
            )

            if not result.facts:
                logger.debug(
                    f"VectorMemory: No new facts extracted for session {session_id}."
                )
                return []

            logger.info(
                f"VectorMemory extracted {len(result.facts)} facts. Saving..."
            )

            # Generate vectors for each fact and save to Qdrant
            chunks = []
            for fact in result.facts:
                vector = await self.embeddings_client.embed_query(fact)
                chunks.append(
                    EmbeddedChunk(
                        text=fact,
                        vector=vector,
                        metadata={
                            "session_id": session_id,
                            "type": "episodic_fact",
                            "method": "agentic_extraction",
                        },
                    )
                )

            await self.vector_store.upsert_documents(
                self.collection_name, chunks
            )
            return result.facts

        except Exception as e:
            logger.error(
                f"VectorMemory failed to extract/store turn facts: {e}",
                exc_info=True,
            )
            return []

    async def get_relevant_facts(self, query: str, limit: int = 5) -> List[str]:
        """Search Qdrant for facts semantically relevant to the query to inject as context.

        Args:
            query: Current user question or query.
            limit: Maximum facts to return.
        """
        await self._ensure_collection()
        try:
            query_vector = await self.embeddings_client.embed_query(query)
            results = await self.vector_store.similarity_search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
            )
            # results: list of dict {"text": str, "score": float, "metadata": dict}
            return [res["text"] for res in results]
        except Exception as e:
            logger.error(
                f"VectorMemory similarity search failed: {e}", exc_info=True
            )
            return []

    async def clear(self) -> bool:
        """Clear all semantic memory by deleting the vector collection."""
        try:
            await self.vector_store.delete_collection(self.collection_name)
            self._collection_created = False
            logger.warning(
                f"VectorMemory collection '{self.collection_name}' has been cleared."
            )
            return True
        except Exception as e:
            logger.error(
                f"VectorMemory failed to clear collection: {e}", exc_info=True
            )
            return False
