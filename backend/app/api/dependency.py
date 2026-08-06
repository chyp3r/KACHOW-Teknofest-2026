import logging
from typing import Any, Optional

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.models import get_embeddings_client
from app.ai.embeddings.service import EmbeddingService
from app.ai.llms import get_fast_llm_client, get_llm_client
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.document_analysis_graph import create_document_analysis_graph
from app.ai.workflows.draft_graph import create_draft_graph
from app.ai.workflows.routing_graph import create_routing_graph
from app.ai.workflows.rag_graph import create_rag_graph
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.core.security import decode_token
from app.infrastructure.database.session import get_db
from app.infrastructure.extractors import get_document_extractor
from app.infrastructure.storage import get_storage_client
from app.infrastructure.vectorstore import get_vector_store
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.repository import DocumentRepository
from app.domains.chat.chat_service import ChatService
from app.domains.chat.repository import ChatMessageRepository, ChatSessionRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.authorization import AuthorizationException
from app.infrastructure.cache import get_cache

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> UserModel:
    """Dependency to retrieve and authenticate the currently logged-in user from the JWT access token."""
    if not token:
        raise AuthenticationException(message="Authentication token is missing.")

    # Check blacklist in Redis
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{token}"):
        raise AuthenticationException(message="Session has been terminated. Please log in again.")

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(message="Invalid token identity.")

    user_repository = UserRepository(db)
    user_service = UserService(user_repository)

    try:
        user = await user_service.get_user_by_id(user_id)
        if not user.is_active:
            raise AuthenticationException(message="User account is not active.")
        return user
    except Exception as exc:
        raise AuthenticationException(message="User not found.") from exc


def require_roles(*allowed_roles: UserRole):
    """Dependency factory that enforces role-based access control on a route."""

    async def _check_role(current_user: UserModel = Depends(get_current_user)) -> UserModel:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise AuthorizationException(message="You do not have permission to perform this action.")
        return current_user

    return _check_role


async def require_auth_if_enabled(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[UserModel]:
    """Enforce authentication only when ``settings.REQUIRE_AUTH`` is True.

    A single conditional dependency rather than two different router wirings,
    so flipping ``REQUIRE_AUTH`` doesn't need a redeploy with different route
    registrations -- see the setting's docstring for why /documents/* and
    /chat/* default to open.

    Returns:
        The authenticated user when ``REQUIRE_AUTH`` is True, otherwise None.
    """
    if not settings.REQUIRE_AUTH:
        return None
    return await get_current_user(token=token, db=db)


# ---------------------------------------------------------------------------
# Document analysis (Görev 1)
# ---------------------------------------------------------------------------
# Lazy singletons following the get_storage_client()/get_vector_store() idiom:
# corpus loading and graph compilation are not free, so only the first request
# pays for them.
_mevzuat_retriever: Optional[HybridRetriever] = None
_document_analysis_graph: Any = None


async def get_mevzuat_retriever() -> HybridRetriever:
    """Build the legislation retriever once per process.

    Uses native Qdrant hybrid search with a pre-saved sparse vocabulary.
    """
    global _mevzuat_retriever
    if _mevzuat_retriever is None:
        import os
        _mevzuat_retriever = HybridRetriever(
            vector_store=get_vector_store(),
            embeddings_client=get_embeddings_client(),
            collection_name=settings.MEVZUAT_COLLECTION_NAME,
            sparse_vocab_path=os.path.join(
                settings.MEVZUAT_CORPUS_DIR, "sparse_vocab.json"
            ),
        )
    return _mevzuat_retriever


async def get_document_analysis_graph(
    retriever: HybridRetriever = Depends(get_mevzuat_retriever),
) -> Any:
    """Compile the document analysis workflow once per process.

    Args:
        retriever: The legislation retriever injected into the graph.

    Returns:
        The compiled LangGraph workflow.
    """
    global _document_analysis_graph
    if _document_analysis_graph is None:
        _document_analysis_graph = create_document_analysis_graph(
            llm_client=get_llm_client(),
            mevzuat_retriever=retriever,
            fast_llm_client=get_fast_llm_client(),
        )
    return _document_analysis_graph


def get_document_repository(db: AsyncSession = Depends(get_db)) -> DocumentRepository:
    """Provide the document ownership/listing registry repository."""
    return DocumentRepository(db)


def get_chat_session_repository(db: AsyncSession = Depends(get_db)) -> ChatSessionRepository:
    """Provide the chat session listing repository."""
    return ChatSessionRepository(db)


def get_chat_message_repository(db: AsyncSession = Depends(get_db)) -> ChatMessageRepository:
    """Provide the chat message log repository."""
    return ChatMessageRepository(db)


def get_document_analysis_service(
    analysis_graph: Any = Depends(get_document_analysis_graph),
    document_repository: DocumentRepository = Depends(get_document_repository),
) -> DocumentService:
    """Provide the document analysis service with its collaborators injected.

    Args:
        analysis_graph: The compiled analysis workflow.
        document_repository: Ownership/listing registry.

    Returns:
        A ready-to-use `DocumentService`.
    """
    return DocumentService(
        storage=get_storage_client(),
        extractor=get_document_extractor(),
        analysis_graph=analysis_graph,
        embedding_service=EmbeddingService(embeddings_client=get_embeddings_client()),
        vector_store=get_vector_store(),
        document_repository=document_repository,
    )

# ---------------------------------------------------------------------------
# Drafting & Routing (Görev 2)
# ---------------------------------------------------------------------------
_draft_graph: Any = None
_routing_graph: Any = None


async def get_draft_graph() -> Any:
    """Compile the document drafting workflow once per process.

    The writer/reviser use the quality tier; the hybrid gate's judge leg runs
    on the fast tier, since it emits a small verdict rather than draft text.
    """
    global _draft_graph
    if _draft_graph is None:
        _draft_graph = create_draft_graph(
            llm_client=get_llm_client(), fast_llm_client=get_fast_llm_client()
        )
    return _draft_graph


async def get_routing_graph() -> Any:
    """Compile the document routing workflow once per process.

    Uses the fast tier: the output is one unit label plus one sentence, so the
    quality model buys nothing here but latency.
    """
    global _routing_graph
    if _routing_graph is None:
        _routing_graph = create_routing_graph(llm_client=get_fast_llm_client())
    return _routing_graph


def get_draft_service(
    draft_graph: Any = Depends(get_draft_graph),
    routing_graph: Any = Depends(get_routing_graph),
) -> DraftService:
    """Provide the draft service with its collaborators injected."""
    return DraftService(
        storage=get_storage_client(),
        extractor=get_document_extractor(),
        draft_graph=draft_graph,
        routing_graph=routing_graph,
    )

# ---------------------------------------------------------------------------
# Chat & Orchestration (Görev 3)
# ---------------------------------------------------------------------------
_rag_graph: Any = None
_planning_graph: Any = None


async def get_rag_graph() -> Any:
    """Compile the RAG workflow once per process."""
    global _rag_graph
    if _rag_graph is None:
        _rag_graph = create_rag_graph(
            llm_client=get_llm_client(),
            hybrid_retriever=await get_mevzuat_retriever(),
        )
    return _rag_graph


async def get_planning_graph(
    document_analysis_graph: Any = Depends(get_document_analysis_graph),
    rag_graph: Any = Depends(get_rag_graph),
    draft_graph: Any = Depends(get_draft_graph),
    routing_graph: Any = Depends(get_routing_graph),
) -> Any:
    """Compile the master planning graph once per process.

    The only graph that gets a checkpointer -- see create_planning_graph's
    docstring for why the sub-graphs deliberately do not.
    """
    global _planning_graph
    if _planning_graph is None:
        from app.infrastructure.checkpointing import get_checkpointer

        _planning_graph = create_planning_graph(
            llm_client=get_llm_client(),
            document_analysis_graph=document_analysis_graph,
            rag_graph=rag_graph,
            draft_graph=draft_graph,
            routing_graph=routing_graph,
            vector_store=get_vector_store(),
            embeddings_client=get_embeddings_client(),
            fast_llm_client=get_fast_llm_client(),
            checkpointer=get_checkpointer(),
        )
    return _planning_graph


def get_chat_service(
    planning_graph: Any = Depends(get_planning_graph),
) -> ChatService:
    """Provide the ChatService."""
    return ChatService(planning_graph=planning_graph)
