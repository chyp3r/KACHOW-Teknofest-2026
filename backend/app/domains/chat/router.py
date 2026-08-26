import json
import logging
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.dependency import (
    get_chat_message_repository,
    get_chat_service,
    get_chat_session_repository,
    get_document_repository,
    get_draft_repository,
    require_auth_if_enabled,
)
from app.api.exceptions.authorization import AuthorizationException
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership, clearance_for
from app.domains.chat.chat_service import ChatService
from app.domains.chat.repository import ChatMessageRepository, ChatSessionRepository
from app.domains.chat.schema.chat_schema import ChatMessageRequest, ChatResumeRequest
from app.domains.documents.repository import DocumentRepository
from app.domains.drafts.model.draft_model import DraftModel
from app.domains.drafts.repository import DraftRepository
from app.domains.users.model.user_model import UserModel
from app.shared.dto.pagination import PaginatedResponse, PaginationParam

logger = logging.getLogger(__name__)


async def _verify_document_access(
    document_id: Optional[str],
    current_user: UserModel,
    document_repository: DocumentRepository,
) -> None:
    """Çağıranın sahibi olmadığı veya erişim yetkisi olmayan bir evrakı ekleyen bir sohbet turunu reddeder.

    Bir evrakın eklenmesi yalnızca asistanın hangi araçları çağırabileceğini
    değiştirir (bkz. app.ai.tools.document_tools'un modül docstring'i) --
    bundan önce hiçbir şey, çağıranın onu eklemesine ilk etapta izin verilip
    verilmediğini kontrol etmiyordu. ADMIN/MANAGER/ROOT yalnızca sahiplik
    yarısını atlar (bkz. ``bypasses_ownership``) -- şirket genelinde her
    evrakı görürler, ama yetki hâlâ geçerlidir (gerçi onlar için hiçbir
    zaman fiilen bağlayıcı olmaz: bkz. ``clearance_for``), ve şirket sınırı
    kimse için asla atlanmaz.

    Bu kaba, tur seviyesindeki kapıdır (bu çağıran bu evrakı ekleyebilir mi
    diye); ``document_tools.py``'nin kendi alım-anında-reddetme kontrolü bunun
    altındaki daha ince taneli olandır, çünkü tek bir turun araçları bu
    kapının hiç görmediği mevzuat aramasına ve diğer içeriğe de dokunabilir.

    Raises:
        AuthorizationException: Evrak farklı bir şirkete kayıtlıysa, veya
            ``current_user``'dan farklı bir sahibe aitse (ve ADMIN/MANAGER/
            ROOT değilse), veya ``current_user``'ın yetkisi evrakın gizlilik
            seviyesini karşılamıyorsa.
    """
    if not document_id:
        return
    document = await document_repository.get_by_id(document_id, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    if document.owner_id != current_user.id and not bypasses_ownership(current_user):
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    try:
        document_level = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_level = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_level)


async def _resolve_revision_draft(
    draft_id: Optional[str],
    current_user: UserModel,
    draft_repository: DraftRepository,
) -> Optional[DraftModel]:
    """Açıkça seçilmiş bir revizyon hedefini çözer ve yetkilendirir."""
    if not draft_id:
        return None
    draft = await draft_repository.get_by_id(draft_id)
    if draft is None:
        raise AuthorizationException(message="Bu taslağı düzenleme izniniz yok.")
    resource = Resource(
        type="draft", id=draft.id, company_id=draft.company_id, owner_id=draft.user_id
    )
    decision = authorize(subject_from_user(current_user), Action.DRAFT_UPDATE, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu taslağı düzenleme izniniz yok.")
    return draft

# Kimlik doğrulama zorunludur (bkz. require_auth_if_enabled) -- bu router'daki
# her rota gerçek, kiracıya bağlı bir current_user taşır.
router = APIRouter(
    prefix="/chat", tags=["chat"], dependencies=[Depends(require_auth_if_enabled)]
)


def make_serializable(obj: Any) -> Any:
    """İş akışı çıktısını özyinelemeli olarak JSON'a dönüştürülebilir değerlere çevirir.

    İş akışı durumu, ``json.dumps``'ın kodlayamadığı LangChain ``Document``
    nesneleri ve Pydantic modelleri taşır, ve ağacın herhangi bir yerindeki
    tek bir kodlanamayan değer tüm SSE akışını durdurur.

    Args:
        obj: İş akışı durumundan herhangi bir değer.

    Returns:
        JSON açısından güvenli ilkel değerlerden oluşan eşdeğer bir yapı.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): make_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_serializable(item) for item in obj]
    if hasattr(obj, "page_content") and hasattr(obj, "metadata"):
        return {
            "page_content": obj.page_content,
            "metadata": make_serializable(obj.metadata),
        }
    if hasattr(obj, "model_dump"):
        try:
            return make_serializable(obj.model_dump(mode="json"))
        except Exception:
            return make_serializable(obj.model_dump())
    return str(obj)


def _sse_response(
    events: AsyncIterator[dict[str, Any]], http_request: Request
) -> StreamingResponse:
    """Bir iş akışı olay akışını paylaşılan SSE taşıma katmanına sarar.

    Devam ettirilen bir çalıştırma tazesiyle tamamen aynı olay kelime
    dağarcığını akıttığı için ``/stream`` ve ``/resume`` tarafından paylaşılır.

    Args:
        events: Servisin asenkron olay üreticisi.
        http_request: İstemci bağlantı kesilmeleri için sorgulanan gelen istek.

    Returns:
        Bir ``text/event-stream`` yanıtı.
    """

    async def event_generator():
        try:
            async for event in events:
                # İstemci uzaklaşır uzaklaşmaz, kimsenin okumayacağı bir yanıt
                # için yerel modeli meşgul tutmak yerine iş akışını durdur.
                if await http_request.is_disconnected():
                    logger.info("Client disconnected; aborting chat stream.")
                    break
                payload = json.dumps(make_serializable(event), ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("Chat stream failed")
            error = json.dumps(
                {"event": "error", "message": "Akış sırasında bir hata oluştu."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx varsayılan olarak proxy'lenen yanıtları arabelleğe alır, bu da
            # akışın tüm amacını boşa çıkarır.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/message", response_model=None)
async def send_chat_message(
    request: ChatMessageRequest,
    service: ChatService = Depends(get_chat_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    draft_repository: DraftRepository = Depends(get_draft_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir sohbet etkileşimini düzenler ve tamamlanmış sonucu döndürür.

    Kullanıcı girdisini, analiz, taslak yazımı, evrak soru-cevap ya da düz
    sohbete mi ihtiyaç duyduğunu çözen ana planlama grafiği üzerinden
    yönlendirir. Çalıştırma insan-döngüde kapısında duraklatıldığında bir
    ``INTERRUPTED`` durumu da döndürebilir; bunu ``POST /chat/resume`` ile
    devam ettirin.
    """
    await _verify_document_access(request.document_id, current_user, document_repository)
    revision_draft = await _resolve_revision_draft(
        request.draft_id, current_user, draft_repository
    )
    clearance = clearance_for(current_user)
    result = await service.handle_message(
        request,
        user_id=current_user.id,
        requester_clearance=clearance.value if clearance else None,
        company_id=current_user.company_id,
        revision_draft=revision_draft,
        user_display_name=current_user.username,
    )
    return SuccessResponse(data=make_serializable(result.model_dump()))


@router.post("/stream")
async def stream_chat_message(
    request: ChatMessageRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    draft_repository: DraftRepository = Depends(get_draft_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=20, window_seconds=60, key_prefix="chat:stream")),
):
    """Bir sohbet etkileşimini düzenler ve ilerleme olaylarını SSE üzerinden akıtır.

    Önce çözümlenmiş thread_id ile ``session`` yayınlar, ardından iş akışı
    aşamaları için ``node_start``/``node_end``/``node_skipped``/
    ``node_error``, üretildikçe canlı metin için ``token``, istemcinin
    çalıştırma bitmeden önce render edebileceği ara çıktı için
    ``partial_result``, ve ya sonlandırıcı bir ``final_result`` ya da,
    çalıştırma insan-döngüde kapısında duraklatıldıysa, insanın
    yanıtlaması gerekeni taşıyan bir ``interrupt`` olayı yayınlar.
    """
    # SSE yanıtına girmeden önce, üretici içinde değil, kontrol edilir; böylece
    # reddedilen bir istek, açılıp hemen genel bir hata bildiren bir akış
    # yerine normal bir 403 alır.
    await _verify_document_access(request.document_id, current_user, document_repository)
    revision_draft = await _resolve_revision_draft(
        request.draft_id, current_user, draft_repository
    )
    user_id = current_user.id
    clearance = clearance_for(current_user)
    return _sse_response(
        service.handle_message_stream(
            request,
            user_id=user_id,
            requester_clearance=clearance.value if clearance else None,
            company_id=current_user.company_id,
            revision_draft=revision_draft,
            user_display_name=current_user.username,
        ),
        http_request,
    )


@router.post("/resume", response_model=None)
async def resume_chat_stream(
    request: ChatResumeRequest,
    http_request: Request,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
    _: None = Depends(rate_limit(max_requests=30, window_seconds=60, key_prefix="chat:resume")),
):
    """İnsan-döngüde kapısında duraklatılmış bir çalıştırmayı SSE üzerinden akıtarak devam ettirir.

    ``action="answer"``, bir taslağın eksik bilgi yer tutucularını yeniden
    üretmeden doldurur. ``action="approve"|"revise"|"reject"``, birim
    yönlendirmesinden önce insan onayına ihtiyaç duyan bir taslağı çözer.
    """
    user_id = current_user.id
    ChatService._verify_thread_ownership(request.session_id, user_id)
    return _sse_response(
        service.resume_stream(
            request.session_id, request, user_id=user_id, company_id=current_user.company_id
        ),
        http_request,
    )


@router.post("/resume/sync", response_model=None)
async def resume_chat_sync(
    request: ChatResumeRequest,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Duraklatılmış bir çalıştırmayı devam ettirir ve tamamlanmış (veya yeniden duraklatılmış) sonucu döndürür."""
    result = await service.resume(
        request.session_id, request, user_id=current_user.id, company_id=current_user.company_id
    )
    return SuccessResponse(data=make_serializable(result.model_dump()))


def _paginated(items: list, total: int, pagination: PaginationParam) -> PaginatedResponse:
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0
    return PaginatedResponse(
        items=items, total=total, page=pagination.page, size=pagination.size, pages=pages
    )


@router.get("/sessions", response_model=None)
async def list_chat_sessions(
    pagination: PaginationParam = Depends(),
    session_repository: ChatSessionRepository = Depends(get_chat_session_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Çağıranın sohbet oturumlarını, en son aktif olanı önce listeler.

    ``user_id=None`` (bir ADMIN/MANAGER/ROOT -- bkz. ``bypasses_ownership``),
    ``GET /documents``'in kuralına uygun olarak *çağıranın kendi şirketi
    içindeki* her oturumu listeler.
    """
    user_id = None if bypasses_ownership(current_user) else current_user.id
    sessions = await session_repository.list_for_user(
        current_user.company_id, user_id, skip=pagination.offset, limit=pagination.limit
    )
    total = await session_repository.count_for_user(current_user.company_id, user_id)
    page_items = [
        {
            "session_id": session.id,
            "title": session.title,
            "document_id": session.document_id,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
        }
        for session in sessions
    ]
    return SuccessResponse(data=_paginated(page_items, total, pagination))


@router.get("/sessions/{session_id}/messages", response_model=None)
async def list_chat_session_messages(
    session_id: str,
    pagination: PaginationParam = Depends(),
    message_repository: ChatMessageRepository = Depends(get_chat_message_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir oturumun mesajlarını konuşma sırasına göre listeler (en eskiden en yeniye).

    Sahiplik, ``ChatService._verify_thread_ownership``'i yeniden kullanır --
    ``/chat/resume``'un başka bir kullanıcının thread'ine dokunmasını zaten
    engelleyen aynı ``user_id:`` öneki kontrolü.

    Raises:
        AuthorizationException: ``session_id``, ``current_user``'dan
            farklı bir kullanıcıya aitse.
    """
    ChatService._verify_thread_ownership(
        session_id, current_user.id
    )
    messages = await message_repository.list_for_session(
        session_id, skip=pagination.offset, limit=pagination.limit
    )
    total = await message_repository.count_for_session(session_id)
    page_items = [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "workflow_status": message.workflow_status,
            "details": message.details,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]
    return SuccessResponse(data=_paginated(page_items, total, pagination))


@router.get("/sessions/{session_id}/state", response_model=None)
async def get_session_state(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Bir oturumun boşta mı, çalışıyor mu, yoksa bir kesintide mi duraklatılmış olduğunu bildirir.

    İstemcinin bir sayfa yenilemesi veya kopan bir SSE bağlantısı sonrası
    kurtarma yapmasını sağlar: ``status`` ``"interrupted"`` ise, devam
    ettirme formunu kaybetmek yerine dönen ``interrupt`` yükünden yeniden
    render edin.
    """
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id gereklidir.")
    state = await service.get_session_state(
        session_id, user_id=current_user.id
    )
    return SuccessResponse(data=state)
