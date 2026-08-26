"""İstek korelasyon (correlation) ID'leri.

``request.state`` yerine bir ``ContextVar`` kullanılır, çünkü değerin, kapsamında
hiç ``Request`` nesnesi bulunmayan koda ulaşması gerekir -- route handler'dan
birkaç çağrı derinlikte, bir LangGraph çağrısı içinde çalışan workflow node
fonksiyonları. Contextvar'lar aynı task'ın asenkron çağrı zinciri boyunca
otomatik olarak yayılır; id'yi router ile bir graph node'u arasındaki her
katmandan açık bir parametre olarak geçirmek, ihtiyaç duyulan yerde onu geri
okumaktan başka bir fayda sağlamadan birçok imzaya dokunmuş olurdu.
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Mevcut isteğin korelasyon id'sini, isteğin dışındaysa ``"-"`` döndürür."""
    return request_id_var.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Bir istek id'si okur veya üretir ve yanıtta geri yansıtır.

    En dışta kayıtlıdır (``main.py``'de son eklenir, çünkü Starlette
    middleware'leri ters kayıt sırasıyla uygular), böylece diğer her
    middleware ve her route handler id zaten ayarlanmışken çalışır.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
