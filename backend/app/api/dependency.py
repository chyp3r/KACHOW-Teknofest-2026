import logging
from typing import Any, Optional

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.summarizer import SummarizerAgent
from app.ai.embeddings.models import get_embeddings_client
from app.ai.embeddings.service import EmbeddingService
from app.ai.llms import (
    get_fast_llm_client,
    get_guard_llm_client,
    get_llm_client,
    get_router_llm_client,
)
from app.ai.retrieval.examples import ExampleRetriever
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.retrieval.mcp_mevzuat import FallbackMevzuatRetriever, McpMevzuatRetriever
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
from app.infrastructure.extractors.vision import EvrenVisionExtractor, OllamaVisionExtractor
from app.infrastructure.storage import get_storage_client
from app.infrastructure.vectorstore import get_vector_store
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.repository import DraftRepository
from app.domains.drafts.service import DraftService as DraftHistoryService
from app.domains.chat.chat_service import ChatService
from app.domains.chat.repository import ChatMessageRepository, ChatSessionRepository
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.domains.users.service import UserService
from app.api.exceptions.authentication import AuthenticationException
from app.api.exceptions.authorization import AuthorizationException
from app.infrastructure.cache import get_cache
# Re-exported so every router keeps importing its dependency callables from
# this one module -- see app.core.authz.dependency's own docstring.
from app.core.authz.dependency import (  # noqa: F401
    get_authz_service,
    require_permission,
    subject_from_user,
)

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
    except Exception as exc:
        raise AuthenticationException(message="User not found.") from exc

    # Best-effort, and cheap in aggregate: `company_metrics.cached_slug` is a
    # permanent in-process cache (a company's slug never changes), so this
    # pays one extra query per company for the life of the process, not per
    # request. ROOT has no company to attribute a request to and is skipped.
    from app.observability import company_metrics

    if user.company_id is not None:
        if company_metrics.cached_slug(user.company_id) is None:
            from app.domains.companies.repository import CompanyRepository

            company = await CompanyRepository(db).get_by_id(user.company_id)
            if company is not None:
                company_metrics.cache_slug(user.company_id, company.slug)
        company_metrics.note_request(user.company_id)

    return user


def require_roles(*allowed_roles: UserRole):
    """Dependency factory that enforces role-based access control on a route.

    A thin shim over the ABAC PDP's ``role_permitted`` (see
    ``app.core.authz.engine``), per the tenancy plan's ABAC design -- so the
    role-membership check every route already relied on lives in one place
    alongside the rest of the engine, rather than being reimplemented here.
    Behaviour is unchanged: same membership test, same exception on a
    mismatch, so no existing route or test changes.
    """
    from app.core.authz.engine import role_permitted

    async def _check_role(current_user: UserModel = Depends(get_current_user)) -> UserModel:
        try:
            role = UserRole(current_user.role)
        except ValueError:
            raise AuthorizationException(message="You do not have permission to perform this action.")
        if not role_permitted(role, allowed_roles):
            raise AuthorizationException(message="You do not have permission to perform this action.")
        return current_user

    return _check_role


async def require_auth_if_enabled(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    """Require an authenticated, tenant-bound user.

    Multi-tenancy made authentication mandatory everywhere: every row in the
    system now carries a ``company_id`` (see the tenancy plan's Faz 1), so
    there is no longer an "unauthenticated demo/dev path" for a request to
    fall back to -- there would be no company to scope its reads/writes to.
    The name is kept (rather than renamed to e.g. ``require_authenticated_
    user``) purely to avoid touching every router's import and
    ``Depends(...)`` call site in this same change; a rename is a fine
    follow-up with no behavioural stakes.

    Returns:
        The authenticated, active user.
    """
    return await get_current_user(token=token, db=db)


# ---------------------------------------------------------------------------
# Document analysis (Görev 1)
# ---------------------------------------------------------------------------
# Lazy singletons following the get_storage_client()/get_vector_store() idiom:
# corpus loading and graph compilation are not free, so only the first request
# pays for them.
_mevzuat_retriever: Optional[HybridRetriever] = None
_document_analysis_mevzuat_retriever: Any = None
_document_analysis_graph: Any = None


async def get_mevzuat_retriever() -> HybridRetriever:
    """Build the local legislation retriever once per process.

    Uses native Qdrant hybrid search with a pre-saved sparse vocabulary. This
    is the *local-corpus* retriever specifically: it also backs the general
    assistant's RAG flow (get_rag_graph, Görev 3), which MEVZUAT_SOURCE does
    not affect -- that switch is scoped to document analysis alone. Document
    analysis's own retriever, which may layer MCP-first retrieval on top of
    this one, is get_document_analysis_mevzuat_retriever below.
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


_example_retriever: Optional[ExampleRetriever] = None


async def get_example_retriever() -> ExampleRetriever:
    """Build the draft few-shot style-example retriever once per process.

    Same idiom and same native Qdrant hybrid search as
    ``get_mevzuat_retriever`` above, targeting the separate
    ``resmi_yazisma_ornek`` collection built by
    ``scripts/index_yazisma_examples.py`` instead of the legislation corpus.
    """
    global _example_retriever
    if _example_retriever is None:
        import os
        hybrid = HybridRetriever(
            vector_store=get_vector_store(),
            embeddings_client=get_embeddings_client(),
            collection_name=settings.RESMI_YAZISMA_COLLECTION_NAME,
            sparse_vocab_path=os.path.join(
                os.path.dirname(settings.RESMI_YAZISMA_EXAMPLES_PATH), "sparse_vocab.json"
            ),
        )
        _example_retriever = ExampleRetriever(hybrid)
    return _example_retriever


#: Same collection name app.ai.tools.document_tools.QA_COLLECTION_NAME and
#: app.domains.documents.service.DocumentService._index_for_qa use --
#: duplicated as a literal, not imported, to keep this module's dependency
#: surface limited to app.ai.* the same way the rest of this file already is.
_DOCUMENT_QA_COLLECTION_NAME = "document_qa"

_document_qa_retriever: Optional[HybridRetriever] = None


async def get_document_qa_retriever() -> HybridRetriever:
    """Build the draft workflow's document-grounding retriever once per process.

    Same idiom as ``get_example_retriever`` above, targeting the
    ``document_qa`` collection populated per-document at upload time (see
    ``DocumentService._index_for_qa``) instead of a fixed offline corpus --
    the assistant's own ``search_document`` tool already queries this same
    collection (``app.ai.tools.document_tools``). No sparse vocab file exists
    for it (there is no single fitted corpus to fit one against), so sparse
    query weights default to 1.0, the same degrade ``get_mevzuat_retriever``
    documents for its own optional vocab path.
    """
    global _document_qa_retriever
    if _document_qa_retriever is None:
        _document_qa_retriever = HybridRetriever(
            vector_store=get_vector_store(),
            embeddings_client=get_embeddings_client(),
            collection_name=_DOCUMENT_QA_COLLECTION_NAME,
        )
    return _document_qa_retriever


async def get_document_analysis_mevzuat_retriever(
    local: HybridRetriever = Depends(get_mevzuat_retriever),
) -> Any:
    """Build document analysis's legislation retriever once per process.

    MEVZUAT_SOURCE="mcp" (default) layers MCP-first retrieval over the same
    local corpus used everywhere else, falling back to it on any failure;
    "local" returns the local retriever directly, unchanged from before this
    setting existed.

    The returned object may or may not have its live cache warmed yet --
    that happens separately (see app.lifespan._warm_up_graphs) so that a
    slow or unreachable MCP server never blocks compiling this graph, only
    delays when the live source starts actually being used.

    Args:
        local: The local-corpus retriever, always constructed regardless of
            source (it is MCP-first's fallback, and local mode's only
            retriever).

    Returns:
        A HybridRetriever (source="local") or a FallbackMevzuatRetriever
        wrapping it (source="mcp"). Both satisfy the same
        `async retrieve(query, limit) -> list[Document]` interface.
    """
    global _document_analysis_mevzuat_retriever
    if _document_analysis_mevzuat_retriever is None:
        if settings.MEVZUAT_SOURCE == "mcp":
            _document_analysis_mevzuat_retriever = FallbackMevzuatRetriever(
                McpMevzuatRetriever(), local
            )
        else:
            _document_analysis_mevzuat_retriever = local
    return _document_analysis_mevzuat_retriever


async def get_document_analysis_graph(
    retriever: Any = Depends(get_document_analysis_mevzuat_retriever),
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
            guard_llm_client=get_guard_llm_client(),
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
    db: AsyncSession = Depends(get_db),
) -> DocumentService:
    """Provide the document analysis service with its collaborators injected.

    Args:
        analysis_graph: The compiled analysis workflow.
        document_repository: Ownership/listing registry.
        db: Shared with the pool repositories below so filing an upload into
            its owner's default pool commits in the same transaction as
            registering the document itself.

    Returns:
        A ready-to-use `DocumentService`.
    """
    from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
    from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository
    from app.domains.quotas.service import QuotaService

    return DocumentService(
        storage=get_storage_client(),
        extractor=get_document_extractor(),
        analysis_graph=analysis_graph,
        embedding_service=EmbeddingService(embeddings_client=get_embeddings_client()),
        vector_store=get_vector_store(),
        document_repository=document_repository,
        pool_repository=DocumentPoolRepository(db),
        pool_item_repository=DocumentPoolItemRepository(db),
        quota_service=QuotaService(UsageCounterRepository(db), CompanyQuotaRepository(db)),
        # Builds the on-demand detailed summary (generate_detailed_summary)
        # -- not part of analysis_graph, since that summary is deliberately
        # not a graph node (see create_document_analysis_graph's own
        # docstring for why). Same llm_client analysis_graph itself uses;
        # SummarizerAgent is cheap to construct (no I/O), so a fresh one per
        # request is fine, mirroring how analysis_graph builds its own
        # per-agent instances internally.
        summarizer_agent=SummarizerAgent(get_llm_client()),
        # Backs reextract_document_text -- the user's manual "Yeniden OCR"
        # override, always a full vision-model pass bypassing
        # get_document_extractor()'s chain entirely (see that method's own
        # docstring for why). A fresh instance per request, same as
        # summarizer_agent above and the vision extractor
        # get_document_extractor() builds internally -- cheap to construct,
        # no I/O until .extract() is actually called.
        vision_extractor=(
            OllamaVisionExtractor() if settings.LOCAL_MODE else EvrenVisionExtractor()
        ),
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
        from app.domains.companies.provider import (
            get_company_adapter,
            get_company_profile,
            get_company_rules,
        )

        _draft_graph = create_draft_graph(
            llm_client=get_llm_client(),
            fast_llm_client=get_fast_llm_client(),
            example_retriever=await get_example_retriever(),
            adapter_provider=get_company_adapter,
            profile_provider=get_company_profile,
            rules_provider=get_company_rules,
            document_qa_retriever=await get_document_qa_retriever(),
        )
    return _draft_graph


async def get_routing_graph() -> Any:
    """Compile the document routing workflow once per process.

    Uses the fast tier: the output is one unit label plus one sentence, so the
    quality model buys nothing here but latency. `units_provider` is a plain
    callable (not resolved once here) so every routing decision re-reads the
    active unit list from the database, even though the graph itself is only
    compiled once.
    """
    global _routing_graph
    if _routing_graph is None:
        from app.domains.units.provider import get_active_units_for_routing

        _routing_graph = create_routing_graph(
            llm_client=get_router_llm_client(), units_provider=get_active_units_for_routing
        )
    return _routing_graph


def get_draft_service(
    draft_graph: Any = Depends(get_draft_graph),
    routing_graph: Any = Depends(get_routing_graph),
    db: AsyncSession = Depends(get_db),
) -> DraftService:
    """Provide the draft service with its collaborators injected.

    `db` only backs `quota_service` here -- the draft itself is still
    persisted through `app.domains.drafts.draft_recorder`'s own independent
    session (see that module's docstring), unchanged.
    """
    from app.domains.quotas.repository import CompanyQuotaRepository, UsageCounterRepository
    from app.domains.quotas.service import QuotaService

    return DraftService(
        storage=get_storage_client(),
        extractor=get_document_extractor(),
        draft_graph=draft_graph,
        routing_graph=routing_graph,
        quota_service=QuotaService(UsageCounterRepository(db), CompanyQuotaRepository(db)),
    )


def get_draft_repository(db: AsyncSession = Depends(get_db)) -> DraftRepository:
    """Provide the draft version-chain repository (see `DraftModel`).

    Read-only DI path -- writes go through `app.domains.drafts.
    draft_recorder`'s own self-contained session (see that module's
    docstring for why).
    """
    return DraftRepository(db)


def get_draft_history_service(
    draft_repository: DraftRepository = Depends(get_draft_repository),
) -> DraftHistoryService:
    """Provide the read-side drafts service backing `GET /drafts`.

    Named distinctly from `get_draft_service`/`DraftService` above (the
    documents domain's drafting *generation* service) to avoid colliding
    with it -- both legitimately are "the draft service" for their own
    domain.
    """
    return DraftHistoryService(draft_repository)

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
    mevzuat_retriever: Any = Depends(get_document_analysis_mevzuat_retriever),
) -> Any:
    """Compile the master planning graph once per process.

    The only graph that gets a checkpointer -- see create_planning_graph's
    docstring for why the sub-graphs deliberately do not.
    """
    global _planning_graph
    if _planning_graph is None:
        from app.domains.companies.provider import (
            get_company_adapter,
            get_company_profile,
            get_company_rules,
        )
        from app.domains.documents.provider import get_cached_document
        from app.domains.transfers.provider import build_transfer_graph_provider
        from app.domains.units.provider import get_active_units_for_routing
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
            guard_llm_client=get_guard_llm_client(),
            checkpointer=get_checkpointer(),
            mevzuat_retriever=mevzuat_retriever,
            adapter_provider=get_company_adapter,
            profile_provider=get_company_profile,
            rules_provider=get_company_rules,
            units_provider=get_active_units_for_routing,
            # Faz 4 (#201) -- always built and injected, gated where the
            # propose_transfer tool is actually offered instead
            # (settings.AI_TRANSFER_ENABLED; see planning_graph._run_assist).
            # Same reason units_provider/adapter_provider are unconditional:
            # an unused provider is inert, and gating construction here
            # would just be a second place the flag has to be checked
            # correctly.
            transfer_provider=build_transfer_graph_provider(),
            document_cache_provider=get_cached_document,
        )
    return _planning_graph


def get_chat_service(
    planning_graph: Any = Depends(get_planning_graph),
) -> ChatService:
    """Provide the ChatService."""
    return ChatService(planning_graph=planning_graph)
