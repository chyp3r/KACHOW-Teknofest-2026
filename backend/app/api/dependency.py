import logging
from typing import Any, Optional

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.embeddings.models import get_embeddings_client
from app.ai.llms import get_llm_client
from app.ai.retrieval.bm25 import BM25Retriever
from app.ai.retrieval.corpus_loader import load_mevzuat_corpus
from app.ai.retrieval.dense import DenseRetriever
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows.document_analysis_graph import create_document_analysis_graph
from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.core.security import decode_token
from app.infrastructure.database.session import get_db
from app.infrastructure.extractors import get_document_extractor
from app.infrastructure.storage import get_storage_client
from app.infrastructure.vectorstore import get_vector_store
from app.domains.documents.service import DocumentService
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
        raise AuthenticationException(message="Kimlik doğrulama token'ı eksik.")

    # Check blacklist in Redis
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{token}"):
        raise AuthenticationException(message="Oturum sonlandırılmış, lütfen tekrar giriş yapın.")

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationException(message="Geçersiz token kimliği.")

    user_repository = UserRepository(db)
    user_service = UserService(user_repository)
    
    try:
        user = await user_service.get_user_by_id(user_id)
        if not user.is_active:
            raise AuthenticationException(message="Kullanıcı hesabı aktif değil.")
        return user
    except Exception as exc:
        raise AuthenticationException(message="Kullanıcı bulunamadı.") from exc

def require_roles(*allowed_roles: UserRole):
    """Dependency generator to enforce role-based access control (RBAC) on endpoints."""
    def role_dependency(current_user: UserModel = Depends(get_current_user)) -> UserModel:
        if current_user.role not in [role.value for role in allowed_roles]:
            raise AuthorizationException(message="Bu işlem için yetkiniz bulunmamaktadır.")
        return current_user
    return role_dependency


# ---------------------------------------------------------------------------
# Document analysis (Görev 1)
# ---------------------------------------------------------------------------
# Lazy singletons following the get_storage_client()/get_vector_store() idiom:
# corpus loading and graph compilation are not free, so only the first request
# pays for them.
_mevzuat_retriever: Optional[HybridRetriever] = None
_document_analysis_graph: Any = None

# Must match scripts/index_mevzuat.py, otherwise the BM25 and dense halves of the
# hybrid retriever chunk the same corpus differently and reciprocal rank fusion --
# which de-duplicates on exact page_content -- counts every shared passage twice.
MEVZUAT_CHUNK_SIZE = 1000
MEVZUAT_CHUNK_OVERLAP = 200


async def get_mevzuat_retriever() -> HybridRetriever:
    """Build the legislation retriever once per process.

    The BM25 half has no persistence layer, so its corpus is re-read from disk
    rather than scrolled back out of the vector store: BM25 needs only text, which
    makes this cheap and independent of Qdrant and Ollama.

    Returns:
        A hybrid dense + BM25 retriever over the legislation collection.
    """
    global _mevzuat_retriever
    if _mevzuat_retriever is None:
        embeddings_client = get_embeddings_client()
        dense = DenseRetriever(
            vector_store=get_vector_store(),
            embeddings_client=embeddings_client,
            collection_name=settings.MEVZUAT_COLLECTION_NAME,
        )
        bm25 = BM25Retriever()
        documents = await load_mevzuat_corpus(
            settings.MEVZUAT_CORPUS_DIR,
            RecursiveChunker(
                chunk_size=MEVZUAT_CHUNK_SIZE, chunk_overlap=MEVZUAT_CHUNK_OVERLAP
            ),
        )
        if documents:
            bm25.index_documents(documents)
        else:
            # Without this warning a missing corpus silently degrades the hybrid
            # retriever to dense-only over an English-centric embedding model.
            logger.warning(
                "Mevzuat corpus is empty at %s; BM25 retrieval is disabled and "
                "legislation suggestions will be weak.",
                settings.MEVZUAT_CORPUS_DIR,
            )
        _mevzuat_retriever = HybridRetriever(
            dense_retriever=dense, bm25_retriever=bm25
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
            llm_client=get_llm_client(), mevzuat_retriever=retriever
        )
    return _document_analysis_graph


def get_document_analysis_service(
    analysis_graph: Any = Depends(get_document_analysis_graph),
) -> DocumentService:
    """Provide the document analysis service with its collaborators injected.

    Args:
        analysis_graph: The compiled analysis workflow.

    Returns:
        A ready-to-use `DocumentService`.
    """
    return DocumentService(
        storage=get_storage_client(),
        extractor=get_document_extractor(),
        analysis_graph=analysis_graph,
    )
