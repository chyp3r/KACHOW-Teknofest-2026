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
# Her router'ın bağımlılık çağrılabilirlerini bu tek modülden içe aktarmaya
# devam etmesi için yeniden dışa aktarılıyor -- bkz. app.core.authz.dependency'nin
# kendi docstring'i.
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
    """JWT erişim token'ından şu anda oturum açmış kullanıcıyı alıp kimliğini doğrulayan bağımlılık."""
    if not token:
        raise AuthenticationException(message="Authentication token is missing.")

    # Redis'te kara listeyi kontrol et
    cache = get_cache()
    if await cache.exists(f"token_blacklist:{token}"):
        raise AuthenticationException(message="Bu oturum sonlandırıldı. Lütfen tekrar giriş yapın.")

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

    # En iyi çaba (best-effort) ve toplamda ucuz: `company_metrics.cached_slug`
    # kalıcı bir süreç-içi önbellektir (bir şirketin slug'ı asla değişmez), bu
    # yüzden bu işlem süreç ömrü boyunca şirket başına bir ek sorgu yapar,
    # istek başına değil. ROOT'un isteği ilişkilendirebileceği bir şirketi
    # olmadığından atlanır.
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
    """Bir route üzerinde rol tabanlı erişim kontrolünü zorunlu kılan bağımlılık fabrikası.

    ABAC PDP'nin ``role_permitted``'ı (bkz. ``app.core.authz.engine``) üzerinde
    ince bir katman -- tenancy planının ABAC tasarımına göre, böylece her
    route'un zaten güvendiği rol-üyeliği kontrolü burada yeniden uygulanmak
    yerine motorun geri kalanıyla birlikte tek bir yerde yaşar. Davranış
    değişmedi: aynı üyelik testi, uyuşmazlıkta aynı istisna, dolayısıyla
    mevcut hiçbir route veya test değişmiyor.
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
    """Kimliği doğrulanmış, tenant'a bağlı bir kullanıcı gerektirir.

    Çoklu kiracılık (multi-tenancy), kimlik doğrulamayı her yerde zorunlu
    hale getirdi: sistemdeki her satır artık bir ``company_id`` taşıyor
    (bkz. tenancy planının Faz 1'i), bu yüzden bir isteğin geri
    düşebileceği bir "kimliksiz demo/dev yolu" artık yok -- okuma/yazmalarını
    kapsayacak bir şirket olmazdı. İsim korundu (örn. ``require_authenticated_
    user`` olarak yeniden adlandırılmadı) yalnızca bu değişiklikte her
    router'ın import'unu ve ``Depends(...)`` çağrı noktasını değiştirmekten
    kaçınmak için; yeniden adlandırma, davranışsal riski olmayan iyi bir
    takip işi olur.

    Returns:
        Kimliği doğrulanmış, aktif kullanıcı.
    """
    return await get_current_user(token=token, db=db)


# ---------------------------------------------------------------------------
# Belge analizi (Görev 1)
# ---------------------------------------------------------------------------
# get_storage_client()/get_vector_store() deyimini izleyen tembel (lazy)
# singleton'lar: korpus yükleme ve graph derlemesi bedava değildir, bu yüzden
# yalnızca ilk istek bunun bedelini öder.
_mevzuat_retriever: Optional[HybridRetriever] = None
_document_analysis_mevzuat_retriever: Any = None
_document_analysis_graph: Any = None


async def get_mevzuat_retriever() -> HybridRetriever:
    """Yerel mevzuat retriever'ını süreç başına bir kez oluşturur.

    Önceden kaydedilmiş bir seyrek (sparse) sözlükle native Qdrant hibrit
    aramayı kullanır. Bu özellikle *yerel-korpus* retriever'ıdır: genel
    asistanın RAG akışını da (get_rag_graph, Görev 3) destekler; MEVZUAT_SOURCE
    bunu etkilemez -- o anahtar yalnızca belge analizini kapsar. Bunun
    üzerine MCP-first retrieval katmanı ekleyebilecek belge analizinin kendi
    retriever'ı ise aşağıdaki get_document_analysis_mevzuat_retriever'dır.
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
    """Taslak few-shot stil-örneği retriever'ını süreç başına bir kez oluşturur.

    Yukarıdaki ``get_mevzuat_retriever`` ile aynı deyim ve aynı native Qdrant
    hibrit arama; mevzuat korpusu yerine ``scripts/index_yazisma_examples.py``
    tarafından oluşturulan ayrı ``resmi_yazisma_ornek`` koleksiyonunu hedefler.
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


#: app.ai.tools.document_tools.QA_COLLECTION_NAME ve
#: app.domains.documents.service.DocumentService._index_for_qa'nın kullandığı
#: aynı koleksiyon adı -- bu modülün bağımlılık yüzeyini, dosyanın geri
#: kalanında olduğu gibi app.ai.* ile sınırlı tutmak için import edilmek
#: yerine literal olarak tekrarlanmıştır.
_DOCUMENT_QA_COLLECTION_NAME = "document_qa"

_document_qa_retriever: Optional[HybridRetriever] = None


async def get_document_qa_retriever() -> HybridRetriever:
    """Taslak iş akışının belgeye-dayanma (document-grounding) retriever'ını süreç başına bir kez oluşturur.

    Yukarıdaki ``get_example_retriever`` ile aynı deyim; sabit bir çevrimdışı
    korpus yerine, yükleme sırasında belge başına doldurulan ``document_qa``
    koleksiyonunu hedefler (bkz. ``DocumentService._index_for_qa``) --
    asistanın kendi ``search_document`` aracı zaten bu aynı koleksiyonu
    sorguluyor (``app.ai.tools.document_tools``). Bunun için bir seyrek
    (sparse) sözlük dosyası yoktur (karşı fit edilecek tek bir korpus yoktur),
    bu yüzden seyrek sorgu ağırlıkları varsayılan olarak 1.0'dır -- tıpkı
    ``get_mevzuat_retriever``'ın kendi opsiyonel sözlük yolu için belgelediği
    aynı düşüş (degrade) gibi.
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
    """Belge analizinin mevzuat retriever'ını süreç başına bir kez oluşturur.

    MEVZUAT_SOURCE="mcp" (varsayılan), her yerde kullanılan aynı yerel
    korpusun üzerine MCP-first retrieval katmanı ekler ve herhangi bir
    hatada ona geri döner; "local" ise yerel retriever'ı doğrudan döndürür,
    bu ayar var olmadan önceki haliyle değişmeden.

    Döndürülen nesnenin canlı önbelleği henüz ısıtılmış olabilir ya da
    olmayabilir -- bu ayrıca gerçekleşir (bkz. app.lifespan._warm_up_graphs)
    böylece yavaş veya erişilemeyen bir MCP sunucusu bu graph'ın derlenmesini
    asla engellemez, yalnızca canlı kaynağın fiilen kullanılmaya
    başlanmasını geciktirir.

    Args:
        local: Kaynaktan bağımsız olarak her zaman oluşturulan yerel-korpus
            retriever'ı (MCP-first'ün yedeği ve yerel modun tek retriever'ı).

    Returns:
        Bir HybridRetriever (source="local") veya onu saran bir
        FallbackMevzuatRetriever (source="mcp"). İkisi de aynı
        `async retrieve(query, limit) -> list[Document]` arayüzünü karşılar.
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
    """Belge analizi iş akışını süreç başına bir kez derler.

    Args:
        retriever: Graph'a enjekte edilen mevzuat retriever'ı.

    Returns:
        Derlenmiş LangGraph iş akışı.
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
    """Belge sahiplik/listeleme kayıt deposunu sağlar."""
    return DocumentRepository(db)


def get_user_repository(db: AsyncSession = Depends(get_db)) -> UserRepository:
    """Provide tenant-scoped user lookups to API routes."""
    return UserRepository(db)


def get_chat_session_repository(db: AsyncSession = Depends(get_db)) -> ChatSessionRepository:
    """Sohbet oturumu listeleme deposunu sağlar."""
    return ChatSessionRepository(db)


def get_chat_message_repository(db: AsyncSession = Depends(get_db)) -> ChatMessageRepository:
    """Sohbet mesajı kayıt deposunu sağlar."""
    return ChatMessageRepository(db)


def get_document_analysis_service(
    analysis_graph: Any = Depends(get_document_analysis_graph),
    document_repository: DocumentRepository = Depends(get_document_repository),
    db: AsyncSession = Depends(get_db),
) -> DocumentService:
    """İş birlikçileri enjekte edilmiş belge analizi servisini sağlar.

    Args:
        analysis_graph: Derlenmiş analiz iş akışı.
        document_repository: Sahiplik/listeleme kaydı.
        db: Aşağıdaki pool repository'leriyle paylaşılır, böylece bir
            yüklemenin sahibinin varsayılan pool'una dosyalanması, belgenin
            kendisini kaydetmekle aynı işlemde (transaction) commit edilir.

    Returns:
        Kullanıma hazır bir `DocumentService`.
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
        # Talep üzerine oluşturulan detaylı özeti (generate_detailed_summary)
        # inşa eder -- analysis_graph'ın bir parçası değildir, çünkü bu özet
        # kasıtlı olarak bir graph node'u değildir (nedeni için
        # create_document_analysis_graph'ın kendi docstring'ine bakın).
        # analysis_graph'ın kendisinin kullandığı aynı llm_client;
        # SummarizerAgent'ı oluşturmak ucuzdur (I/O yok), bu yüzden istek
        # başına yeni bir tane oluşturmak sorun değildir -- analysis_graph'ın
        # kendi ajan başına örnekleri dahili olarak nasıl inşa ettiğini
        # yansıtır.
        summarizer_agent=SummarizerAgent(get_llm_client()),
        # reextract_document_text'i destekler -- kullanıcının manuel "Yeniden
        # OCR" geçersiz kılması, get_document_extractor()'ın zincirini
        # tamamen atlayarak her zaman tam bir vision-model geçişi yapar
        # (nedeni için o metodun kendi docstring'ine bakın). Yukarıdaki
        # summarizer_agent ve get_document_extractor()'ın dahili olarak
        # inşa ettiği vision extractor ile aynı şekilde istek başına yeni
        # bir örnek -- oluşturmak ucuzdur, .extract() fiilen çağrılana
        # kadar I/O yoktur.
        vision_extractor=(
            OllamaVisionExtractor() if settings.LOCAL_MODE else EvrenVisionExtractor()
        ),
    )

# ---------------------------------------------------------------------------
# Taslak Oluşturma & Yönlendirme (Görev 2)
# ---------------------------------------------------------------------------
_draft_graph: Any = None
_routing_graph: Any = None


async def get_draft_graph() -> Any:
    """Belge taslak oluşturma iş akışını süreç başına bir kez derler.

    Yazar/revizör kalite katmanını kullanır; hibrit kapının hakem bacağı
    hızlı katmanda çalışır, çünkü taslak metin yerine küçük bir karar
    üretir.
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
    """Belge yönlendirme iş akışını süreç başına bir kez derler.

    Hızlı katmanı kullanır: çıktı bir birim etiketi artı bir cümledir, bu
    yüzden kalite modeli burada yalnızca gecikme (latency) kazandırır.
    `units_provider` düz bir çağrılabilir'dir (burada bir kez çözülmez), bu
    yüzden graph'ın kendisi yalnızca bir kez derlense de her yönlendirme
    kararı aktif birim listesini veritabanından yeniden okur.
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
    """İş birlikçileri enjekte edilmiş taslak servisini sağlar.

    `db` burada yalnızca `quota_service`'i destekler -- taslağın kendisi
    hâlâ `app.domains.drafts.draft_recorder`'ın kendi bağımsız oturumu
    üzerinden kalıcı hale getirilir (bkz. o modülün docstring'i), değişmeden.
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
    """Taslak sürüm-zinciri deposunu sağlar (bkz. `DraftModel`).

    Salt-okunur DI yolu -- yazmalar `app.domains.drafts.
    draft_recorder`'ın kendi kendine yeten oturumu üzerinden gider
    (nedeni için o modülün docstring'ine bakın).
    """
    return DraftRepository(db)


def get_draft_history_service(
    draft_repository: DraftRepository = Depends(get_draft_repository),
) -> DraftHistoryService:
    """`GET /drafts`'ı destekleyen okuma-tarafı taslaklar servisini sağlar.

    Yukarıdaki `get_draft_service`/`DraftService`'ten (documents alanının
    taslak *üretim* servisi) farklı adlandırıldı, çakışmayı önlemek için --
    ikisi de kendi alanları için meşru olarak "taslak servisi"dir.
    """
    return DraftHistoryService(draft_repository)

# ---------------------------------------------------------------------------
# Sohbet & Orkestrasyon (Görev 3)
# ---------------------------------------------------------------------------
_rag_graph: Any = None
_planning_graph: Any = None


async def get_rag_graph() -> Any:
    """RAG iş akışını süreç başına bir kez derler."""
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
    """Ana planlama graph'ını süreç başına bir kez derler.

    Checkpointer alan tek graph budur -- alt-graph'ların neden kasıtlı
    olarak almadığı için create_planning_graph'ın docstring'ine bakın.
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
            # Faz 4 (#201) -- her zaman oluşturulur ve enjekte edilir; kapı
            # (gate) bunun yerine propose_transfer aracının fiilen sunulduğu
            # yerdedir (settings.AI_TRANSFER_ENABLED; bkz.
            # planning_graph._run_assist). units_provider/adapter_provider'ın
            # koşulsuz olmasıyla aynı sebep: kullanılmayan bir provider
            # etkisizdir, ve inşayı burada kapılamak yalnızca bayrağın doğru
            # kontrol edilmesi gereken ikinci bir yer olurdu.
            transfer_provider=build_transfer_graph_provider(),
            document_cache_provider=get_cached_document,
        )
    return _planning_graph


def get_chat_service(
    planning_graph: Any = Depends(get_planning_graph),
) -> ChatService:
    """ChatService'i sağlar."""
    return ChatService(planning_graph=planning_graph)
