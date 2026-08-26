"""Herhangi bir DB oturumu açılmadan önce çağıranın tenant kimliğini çözer.

``app.infrastructure.database.session.get_db``, bir oturum açtığı anda
isteğin ``company_id``/root olup olmadığını bilmek zorundadır, çünkü RLS
politikalarının (migration ``0013_rls``) dayandığı Postgres GUC'lerini
ayarlaması gerekir -- ancak ``get_db``'nin kendisinin isteğe erişimi yoktur
ve ``Depends(get_current_user)`` bunu ona vermek için önce çalışamaz: o
bağımlılık kullanıcıyı bulmak için kendi DB oturumuna ihtiyaç duyar; bu da
tam olarak kapsamlandırılmaya çalışılan oturumdur. Bu middleware, JWT'yi
doğrudan çözerek (token zaten ``company_id``/``role`` claim'lerini taşır --
bkz. ``AuthService.authenticate_user``) ve istek herhangi bir bağımlılığa
ulaşmadan önce bunları bir ``ContextVar``'a yayınlayarak bu döngüyü kırar.

Tasarım gereği en iyi çaba (best-effort) ile çalışır ve hata durumunda
sessiz kalır: eksik veya geçersiz bir token burada tamamen normaldir
(anonim bir istek, `/auth/login`'in kendisi veya gerçek kimlik doğrulama
kontrolü henüz çalışmamış bir istek) ve hata fırlatmamalıdır -- bu iş,
sonrasında `get_current_user`/`require_auth_if_enabled`'a aittir. Bu
middleware yalnızca bir isteğin *görebileceklerini* daraltır; bir isteğin
kimlik doğrulaması yapılıp yapılmadığına asla karar vermez.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import TenantContext, current_tenant_var
from app.core.enums.user_role import UserRole
from app.core.security import decode_token

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "


class TenantContextMiddleware(BaseHTTPMiddleware):
    """JWT'nin ``company_id``/``role`` claim'lerini ``current_tenant_var``'a yayınlar.

    ``CorrelationIdMiddleware`` ile birlikte kayıtlıdır (bkz. ``app.main``) --
    aynı ``ContextVar``-token-ve-reset şekli kullanılır, böylece değer istek
    nasıl sonlanırsa sonlansın, isteğin sonunda her zaman temizlenir.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith(_BEARER_PREFIX):
            raw_token = auth_header[len(_BEARER_PREFIX):]
            try:
                payload = decode_token(raw_token)
            except Exception:
                # Süresi dolmuş/bozuk/eksik -- bunu raporlamak bu
                # middleware'in işi değil. İstek tenant context'i olmadan
                # devam eder; route gerçekten kimlik doğrulama gerektiriyorsa
                # bunu kendi kurallarına göre request-auth bağımlılıkları
                # reddedecektir.
                payload = None
            if payload is not None:
                token = current_tenant_var.set(
                    TenantContext(
                        company_id=payload.get("company_id"),
                        is_root=payload.get("role") == UserRole.ROOT.value,
                    )
                )
        try:
            return await call_next(request)
        finally:
            if token is not None:
                current_tenant_var.reset(token)
