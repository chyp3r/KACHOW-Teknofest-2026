from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.ai.workflows.correspondence import CORRESPONDENCE_TYPE_LABELS
from app.api.dependency import (
    get_document_analysis_service,
    get_document_repository,
    get_draft_service,
    get_user_repository,
    require_auth_if_enabled,
)
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.validation import ValidationException
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.constants import MAX_FILE_SIZE_BYTES
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership, clearance_for
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.schema.document_schema import (
    DocumentFieldsUpdateSchema,
    DocumentTextUpdateSchema,
    DraftRequestSchema,
)
from app.infrastructure.extractors.base import DocumentExtractionError
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.shared.dto.pagination import PaginatedResponse, PaginationParam
from app.shared.validator.storage_path_validator import validate_storage_path

# dependencies=[...] bu router'daki her rotaya uygulanır -- kimlik doğrulama
# zorunludur (bkz. require_auth_if_enabled), bu yüzden buradaki her istek
# gerçek, kiracıya bağlı bir current_user taşır.
router = APIRouter(
    prefix="/documents", tags=["documents"], dependencies=[Depends(require_auth_if_enabled)]
)

#: 1 MiB'lik parçalar halinde okunur, böylece toplam, istemciden bir sonraki
#: parça istenmeden önce sınıra karşı kontrol edilebilir.
_READ_CHUNK_BYTES = 1 << 20


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Bir UploadFile'ın gövdesini asla ``limit``'ten fazlasını belleğe almadan okur.

    ``await file.read()``, herhangi bir boyut kontrolü çalışmadan önce
    gövdenin tamamını belleğe okur -- yapılandırılmış 50MB sınırından
    bağımsız olarak 2GB'lık bir yükleme 2GB ayırır, çünkü sınır yalnızca
    sonradan kontrol ediliyordu. Bu fonksiyon, toplam ``limit``'i geçtiği
    anda hata fırlatır, bu yüzden en kötü durumda bellek kullanımı
    ``limit + _READ_CHUNK_BYTES`` ile sınırlı kalır.

    Args:
        file: Gelen yükleme.
        limit: Bayt cinsinden izin verilen azami boyut.

    Returns:
        En fazla ``limit`` bayt olması garanti edilen tam dosya içeriği.

    Raises:
        ValidationException: Gövde ``limit``'i aşarsa.
    """
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValidationException(
                message="Yüklenen dosya izin verilen azami boyutu aşıyor.",
                details={"max_size_bytes": limit},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _authorize_document(current_user: UserModel, document: DocumentModel, action: str) -> None:
    """Aşağıdaki her rotanın satır içinde tekrarladığı
    ``owner_id``/``bypasses_ownership`` kontrolünün yerine geçen tek bir
    ABAC kararı.

    DB destekli ``AuthzService`` yerine yalın, izinsiz ``engine.authorize``
    (yalnızca yerleşik rol kuralları) çağrılır: ``bypasses_ownership``'in
    önceki tam semantiğini yeniden üretir (ADMIN/MANAGER/ROOT şirket
    genelinde her evrakı görür, EMPLOYEE yalnızca kendisininkini), bu sık
    kullanılan yol üzerinde yeni bir istek başına DB/Redis gidiş-dönüşü
    olmadan. Burada ``permission_grants``'a da başvurmak, bu değişiklikte
    bir eksiklik değil, bir çağıranın rolün ötesinde evrak erişimini
    fiilen devretmesi gerektiğinde doğal bir takip adımıdır -- bkz. Faz 2
    sorunu.

    Raises:
        AuthorizationException: ``authorize()`` reddederse.
    """
    resource = Resource(
        type="document", id=document.id, company_id=document.company_id, owner_id=document.owner_id
    )
    decision = authorize(subject_from_user(current_user), action, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")


@router.post("/analyze", response_model=None)
async def analyze_document(
    http_request: Request,
    file: UploadFile = File(..., description="Analiz edilecek evrak dosyası."),
    service: DocumentService = Depends(get_document_analysis_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=10, window_seconds=60, key_prefix="documents:analyze")),
):
    """Gelen bir resmi evrakın ilk incelemesini (ön inceleme) yapar.

    Evrakı doğrudan metin çıkarımı veya OCR ile okur, türünü belirler,
    başlık alanlarını çıkarır, gerekli ama eksik bilgileri ilgili
    mevzuatla birlikte bildirir ve kısa bir özet döndürür.

    Args:
        http_request: Gövde hiç okunmadan önce beyan edilmiş bir
            Content-Length için kontrol edilen ham istek.
        file: Yüklenen evrak.
        service: Enjekte edilmiş evrak analiz servisi.
        current_user: Kimliği doğrulanmış çağıran -- daha sonraki okumaların
            kendisiyle sınırlandırılabilmesi için evrakın sahibi ve şirketi
            olarak kaydedilir.

    Returns:
        Analiz sonucu, birleşik başarı zarfının içinde.
    """
    declared_length = http_request.headers.get("content-length")
    if declared_length is not None and declared_length.isdigit():
        if int(declared_length) > MAX_FILE_SIZE_BYTES:
            raise ValidationException(
                message="Yüklenen dosya izin verilen azami boyutu aşıyor.",
                details={"max_size_bytes": MAX_FILE_SIZE_BYTES},
            )

    content = await _read_bounded(file, MAX_FILE_SIZE_BYTES)
    result = await service.analyze_document(
        file_name=file.filename or "evrak",
        content=content,
        content_type=file.content_type,
        owner_id=current_user.id,
        company_id=current_user.company_id,
    )
    # mode="json" zorunludur: yanıt zarfı, iç içe Pydantic modellerini veya
    # enum üyelerini işleyemeyen json.dumps ile serileştirilir.
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.post("/draft", response_model=None)
async def generate_draft(
    request: DraftRequestSchema,
    service: DraftService = Depends(get_draft_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Resmi bir taslak ve birim yönlendirme önerisi üretir (Görev 2).

    Doğru yazışma türünü belirlemek, metni yazmak ve uygun birime
    yönlendirmek için ilk incelemenin (Görev 1) çıktısını kullanır.

    ``DraftService``, kaynak evrakı doğrudan depodan ``storage_path`` ile
    okur -- ``GET /documents/{storage_path}``'ın aksine, kendi
    sahiplik/yetki kavramı yoktur, bu yüzden bu kontrol burada, router
    sınırında, ham dosya içeriği taslak yazım grafiğine ulaşmadan önce
    yapılmalıdır.

    Raises:
        AuthorizationException: Evrak farklı bir şirkete aitse, veya
            ``current_user``'dan farklı bir sahibe aitse (ve ADMIN/MANAGER/
            ROOT değilse), veya ``current_user``'ın yetkisi evrakın gizlilik
            seviyesini karşılamıyorsa.
    """
    document = await document_repository.get_by_id(request.storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)
    try:
        document_level = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_level = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_level)

    result = await service.generate_draft_and_route(
        request, user_id=current_user.id, company_id=current_user.company_id
    )
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("", response_model=None)
async def list_documents(
    pagination: PaginationParam = Depends(),
    document_repository: DocumentRepository = Depends(get_document_repository),
    user_repository: UserRepository = Depends(get_user_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Yüklenen evrakları özet meta verileriyle birlikte en yeniden en eskiye listeler.

    Args:
        pagination: Sayfa/boyut sorgu parametreleri.
        document_repository: Sahiplik/listeleme kaydı.
        current_user: Kimliği doğrulanmış çağıran -- liste, ADMIN/MANAGER/
            ROOT (bkz. ``bypasses_ownership``) olmadığı sürece sahip olduğu
            evraklarla sınırlıdır; bunlar şirket genelinde her evrakı görür.
            Rolden bağımsız olarak asla şirketler arası değildir.

    Returns:
        7 alanlı kütüphane izdüşümü üzerinde sayfalanmış bir zarf (tam
        analiz için bkz. ``GET /documents/{storage_path}``). Şirket geneli
        görüntüleyiciler ayrıca yükleyenin kullanıcı adını da alır.
    """
    company_wide = bypasses_ownership(current_user)
    owner_id = None if company_wide else current_user.id
    documents = await document_repository.list_for_owner(
        current_user.company_id, owner_id, skip=pagination.offset, limit=pagination.limit
    )
    total = await document_repository.count_for_owner(current_user.company_id, owner_id)
    uploader_usernames = (
        await user_repository.get_usernames_by_ids(
            current_user.company_id, {document.owner_id for document in documents}
        )
        if company_wide and documents
        else {}
    )

    page_items = [
        {
            "file_name": document.file_name,
            "storage_path": document.id,
            "upload_time": document.created_at.isoformat(),
            "document_type": document.document_type,
            "document_type_label": document.document_type_label,
            "compliance_status": document.compliance_status,
            "summary": document.summary,
            "uploader_username": uploader_usernames.get(document.owner_id),
        }
        for document in documents
    ]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0

    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items,
            total=total,
            page=pagination.page,
            size=pagination.size,
            pages=pages,
        ).model_dump()
    )


@router.get("/correspondence-types", response_model=None)
async def list_correspondence_types():
    """Desteklenen giden yazışma türlerini ve Türkçe etiketlerini listeler.

    Etiketlerin TypeScript'te yeniden yazılıp
    ``app.ai.workflows.correspondence.CORRESPONDENCE_TYPE_LABELS``'tan
    sapması yerine, ön yüzün tür seçicisi için tek doğruluk kaynağıdır.
    """
    return SuccessResponse(
        data=[
            {"value": correspondence_type.value, "label": label}
            for correspondence_type, label in CORRESPONDENCE_TYPE_LABELS.items()
        ]
    )


@router.get("/graph", response_model=None)
async def get_corpus_graph(
    service: DocumentService = Depends(get_document_analysis_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=30, window_seconds=60, key_prefix="documents:graph")),
):
    """Çağıranın görebileceği her evrak üzerindeki uyumluluk bilgi grafiği.

    Aşağıdaki her ``/{storage_path:path}`` rotasının üzerinde burada
    tanımlanmıştır -- FastAPI rotaları kayıt sırasına göre eşleştirir ve
    ``:path`` dönüştürücüleri eğik çizgileri yutar, bu yüzden yakalayıcı
    ``GET /{storage_path:path}``'dan sonra kaydedilen düz bir ``/graph``
    asla ulaşılamaz olurdu; her istek önce ``storage_path="graph"`` ile
    yakalayıcıyla eşleşirdi.

    Bu dosyadaki diğer her rotanın aksine, çağıranın yetkisinin üzerindeki
    bir evrak tüm grafik için 403 değildir -- sessizce hariç tutulur (bkz.
    ``DocumentService.build_corpus_graph``'ın kendi docstring'i) ve yalnızca
    sayısı ``hidden_document_count`` olarak geri bildirilir. Gizli bir
    evrakın *var olduğunu* açığa çıkarmak, onu gizlemenin amacını boşa
    çıkarırdı.

    Args:
        service: Enjekte edilmiş evrak analiz servisi.
        current_user: Kimliği doğrulanmış çağıran. ADMIN/MANAGER/ROOT ise
            şirket geneli (bkz. ``bypasses_ownership``), aksi halde
            çağıranın kendi evraklarıyla sınırlı -- ``GET /documents``'in
            zaten kullandığı aynı semantik.

    Returns:
        Birleşik başarı zarfı içinde ``{nodes, edges, insights, truncated,
        total_document_count, hidden_document_count}``.
    """
    owner_id = None if bypasses_ownership(current_user) else current_user.id
    # clearance_for, tanınmayan bir rol için None döner (bkz. kendi
    # docstring'i: "bilinmeyen yetki hiçbir şeyi temizlemez") -- servisin
    # her zaman gerçek bir SensitivityLevel beklediği bir karşılaştırmaya
    # None geçirmek yerine, en düşük seviyeye güvenli şekilde düş.
    clearance = clearance_for(current_user) or SensitivityLevel.UNMARKED
    result = await service.build_corpus_graph(
        current_user.company_id, owner_id, clearance
    )
    return SuccessResponse(data=result)


@router.patch("/{storage_path:path}/fields", response_model=None)
async def update_document_fields(
    storage_path: str,
    payload: DocumentFieldsUpdateSchema,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir evrakın çıkarılan alanlarını elle düzeltir.

    Çıkarımın kaçırdığı veya yanlış aldığı alanlar için arayüz odaklı bir
    düzeltme (bkz. ``DocumentAnalysisPanel`` -- önceden salt okunurdu).
    Orijinal analizin kullandığı aynı deterministik uyumluluk kontrolünü
    (``app.ai.compliance.checker.check_required_fields``, LLM çağrısı yok)
    yeniden çalıştırır, böylece ``missing_fields``/``compliance_status``,
    çıkarımın bulduğu değerde takılı kalmak yerine düzeltmeyi hemen yansıtır.

    Args:
        storage_path: Evrakın depo anahtarı.
        payload: Düzeltilmiş tam alan kümesi.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: Güncellemeden önce kontrol edilen sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        ``GET /documents/{storage_path}`` ile aynı biçimde güncellenmiş analiz.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_UPDATE)

    result = await service.update_document_fields(storage_path, payload.fields, current_user.company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.post("/{storage_path:path}/detailed-summary", response_model=None)
async def generate_detailed_summary(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(
        rate_limit(max_requests=5, window_seconds=60, key_prefix="documents:detailed-summary")
    ),
):
    """Bir evrakın ayrıntılı özetini oluşturur (veya zaten oluşturulmuşsa döndürür).

    Talep üzerine: `POST /documents/analyze`'ın zaten döndürdüğü kısa
    ``summary`` çoğu evrak için yeterlidir, ve ayrıntılı olanı oluşturmak
    maliyetlidir -- doğrudan ölçülmüştür, gerçek evraklarda 184-288sn,
    birkaç ardışık LLM çağrısı (bkz. ``app.ai.summarization``'ın modül
    docstring'i). Bu yüzden istekli analizin bir parçası yerine kendi başına
    bir uç noktadır: bir kullanıcı bu maliyeti yalnızca sonucu gerçekten
    istediğinde öder, her yüklemede değil.

    İdempotent: ayrıntılı özeti zaten önbelleğe alınmış bir evrak, model
    çağrısı olmadan onu hemen döndürür. Tam olarak modele ulaşan her
    çağrının bu kadar pahalı olması nedeniyle
    ``POST /documents/analyze``'den (5/60sn ve 10/60sn) daha sıkı hız
    sınırlıdır.

    Args:
        storage_path: Evrakın depo anahtarı.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: Üretmeden önce kontrol edilen sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        ``detailed_summary`` doldurulmuş tam analiz, ``GET
        /documents/{storage_path}`` ile aynı biçimde.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
        AIException: Özeti oluşturmak zaman aşımına uğrarsa veya alttaki
            sağlayıcı çağrısı başarısız olursa 502 (bunun neden sessizce
            bozulmak yerine hata fırlattığı için bkz.
            ``DocumentService.generate_detailed_summary``'nin kendi
            docstring'i).
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_UPDATE)

    result = await service.generate_detailed_summary(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("/{storage_path:path}/graph", response_model=None)
async def get_document_graph(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Tek evrak komşuluğu: bir evrak ve dokunduğu her madde/kanun.

    Aşağıdaki yakalayıcı ``GET /{storage_path:path}``'ın üzerinde
    tanımlanmıştır -- ikisi de aynı yol biçimiyle eşleşen GET rotalarıdır,
    bu yüzden ``/documents/uploads/abc.pdf/graph`` gibi bir isteğin
    hangisine ulaşacağına yalnızca kayıt sırası karar verir. Ondan sonra
    kaydedilseydi, bu rotaya asla ulaşılamazdı; her böyle bir istek bunun
    yerine ``storage_path="uploads/abc.pdf/graph"`` ile yakalayıcıyla
    eşleşirdi.

    Args:
        storage_path: Evrakın depo anahtarı.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: İçeriği döndürmeden önce kontrol edilen
            sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        ``GET /documents/graph`` ile aynı zarf biçimi, bu tek evrakla
        sınırlı.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)

    result = await service.build_document_graph(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    try:
        document_sensitivity = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_sensitivity = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_sensitivity)

    return SuccessResponse(data=result)


@router.get("/{storage_path:path}/text", response_model=None)
async def get_document_text(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Daha önce analiz edilmiş bir evrakın çıkarılan/OCR metnini döndürür.

    "Belge metni" panel bölümünü destekler. Bilerek aşağıdaki yakalayıcı
    ``GET /{storage_path:path}``'ın ÜZERİNDE tanımlanmıştır: o rota
    açgözlüdür ve aksi halde ``.../text``'i sanki kendisi bir
    ``storage_path``'mış gibi yutardı. ``/fields`` ve ``/detailed-summary``
    rotaları yalnızca farklı HTTP yöntemleri kullandıkları için onun altında
    durabiliyor; bir ``GET`` alt rotasının böyle bir lüksü yoktur.

    Args:
        storage_path: Evrakın depo anahtarı.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: İçeriği döndürmeden önce kontrol edilen
            sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        Önbelleğe alınmış sayfalar/metin artı çıkarım kaynağı, birleşik
        başarı zarfının içinde.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)

    result = await service.get_document_text(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    try:
        document_level = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_level = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.put("/{storage_path:path}/text", response_model=None)
async def update_document_text(
    storage_path: str,
    payload: DocumentTextUpdateSchema,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(
        rate_limit(max_requests=10, window_seconds=60, key_prefix="documents:text")
    ),
):
    """Elle düzeltilmiş OCR/çıkarım metnini kaydeder.

    Çıkarım hattının hâlâ yanlış aldığı metin için arayüz odaklı bir
    düzeltme -- ``FallbackDocumentExtractor``'daki alan bilinçli çıkarım
    kabul düzeltmesinin eşlikçisi: başlığı hâlâ ayrıştırılamayan (veya
    otomatik kuralın eşiği aşılmadığı için hiç yükseltilmeyen) bir evrak
    doğrudan düzeltilebilir. ``fields``, ``missing_fields``,
    ``compliance_status`` ve ``guardrail``'ı düzeltilmiş metinden
    deterministik olarak yeniden türetir -- model çağrısı yok (bkz.
    ``DocumentService.update_document_text``'in kendi docstring'i).

    Args:
        storage_path: Evrakın depo anahtarı.
        payload: Düzeltilmiş sayfa bazlı metin.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: Güncellemeden önce kontrol edilen sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        ``GET /documents/{storage_path}`` ile aynı biçimde güncellenmiş analiz.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
        ValidationException: Gönderilen sayfa sayısı önbelleğe alınmış
            evrakınkiyle eşleşmiyorsa 422.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_UPDATE)

    result = await service.update_document_text(
        storage_path, payload.pages, current_user.company_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.post("/{storage_path:path}/re-extract", response_model=None)
async def reextract_document_text(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(
        rate_limit(max_requests=2, window_seconds=60, key_prefix="documents:reextract")
    ),
):
    """OCR'ı doğrudan görü modeliyle yeniden çalıştırır -- çıkarım zincirinin
    kendi otomatik yükseltmesi tetiklenmediğinde kullanılan manuel geçersiz kılma.

    ``get_document_extractor()``'ın zincirini tamamen atlar ve her zaman
    tam glm-ocr maliyetini öder (bkz.
    ``DocumentService.reextract_document_text``'in kendi docstring'i) --
    bu, tetiklediği çağrının fiilen ne kadar pahalı olduğuyla uyumlu olarak
    bilinçli şekilde ``PUT .../text``'ten (2/60sn ve 10/60sn) veya
    ``POST .../detailed-summary``'den (5/60sn) daha pahalı ve daha sıkı
    hız sınırlıdır.

    Args:
        storage_path: Evrakın depo anahtarı.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: Yeniden çalıştırmadan önce kontrol edilen
            sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        ``GET /documents/{storage_path}`` ile aynı biçimde güncellenmiş analiz.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete veya kullanıcıya
            aitse, veya isteği yapanın yetkisi evrakın gizlilik seviyesini
            karşılamıyorsa 403.
        ValidationException: Görü modeli çağrısının kendisi başarısız olursa 422.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_UPDATE)

    try:
        result = await service.reextract_document_text(storage_path, current_user.company_id)
    except DocumentExtractionError as exc:
        raise ValidationException(
            message="Belge yeniden OCR ile işlenemedi.", details={"reason": str(exc)}
        ) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("/{storage_path:path}", response_model=None)
async def get_document_analysis(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Daha önce hesaplanmış bir analizi tam olarak döndürür.

    ``GET /documents`` her zaman yalnızca 7 alanlı kütüphane izdüşümünü
    döndürür (document_type_label, compliance_status, summary, ...); o
    listeden bir evrakı yeniden seçmek, bu uç noktanın geri okuduğu
    önbelleğe alınmış analizi hiçbir şey açığa çıkarmadığından
    ``missing_fields`` ve ``mevzuat_references``'ı tamamen kaybediyordu.

    Args:
        storage_path: Evrakın depo anahtarı (``POST /documents/analyze``'ın
            döndürdüğü şekilde).
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: İçeriği döndürmeden önce kontrol edilen
            sahiplik kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        Tam analiz, birleşik başarı zarfının içinde.

    Raises:
        HTTPException: storage_path bozuksa 400, onun için önbelleğe
            alınmış bir analiz yoksa 404.
        AuthorizationException: Evrak farklı bir şirkete, veya isteği
            yapandan farklı bir kullanıcıya aitse (ve ADMIN/MANAGER/ROOT
            değilse), veya isteği yapanın yetkisi evrakın gizlilik
            seviyesini karşılamıyorsa 403.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)

    result = await service.get_cached_analysis(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.delete("/{storage_path:path}", response_model=None)
async def delete_document(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir evrakı kalıcı olarak siler: kayıt satırı, ham dosya, analiz
    önbelleği ve indekslenmiş her Soru-Cevap parçası.

    Args:
        storage_path: Evrakın depo anahtarı.
        service: Enjekte edilmiş evrak analiz servisi.
        document_repository: Silmeden önce kontrol edilen sahiplik/listeleme
            kaydı.
        current_user: Kimliği doğrulanmış çağıran.

    Returns:
        Birleşik başarı zarfı içinde ``{"deleted": true}``. ``storage_path``
        zaten yoksa bile başarılı olur -- silme idempotenttir.

    Raises:
        HTTPException: storage_path bozuksa 400.
        AuthorizationException: Evrak farklı bir şirkete, veya
            ``current_user``'dan farklı bir kullanıcıya aitse (ve
            ADMIN/MANAGER/ROOT değilse), veya ``current_user``'ın yetkisi
            evrakın gizlilik seviyesini karşılamıyorsa 403.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is not None:
        _authorize_document(current_user, document, Action.DOCUMENT_DELETE)
        try:
            document_level = SensitivityLevel(document.sensitivity_level)
        except ValueError:
            document_level = SensitivityLevel.UNMARKED
        assert_clearance(current_user, document_level)

    await service.delete_document(storage_path, current_user.company_id)
    return SuccessResponse(data={"deleted": True})
