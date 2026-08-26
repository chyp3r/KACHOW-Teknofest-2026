"""Bir ``ContextVar`` aracılığıyla yayılan, istek kapsamlı kiracı bağlamı.

``app.api.middleware.correlation``'ın ``request_id_var``'ı ile aynı gerekçe:
değerin, kapsamında hiçbir ``Request`` nesnesi olmayan
``app.infrastructure.database.session.get_db``'ye ulaşması gerekir, ve bir
``ContextVar`` aynı görevin asenkron çağrı zinciri boyunca otomatik olarak
yayılır -- bunu middleware ile ``get_db`` arasındaki her dependency
imzasından geçirmek, ihtiyaç duyulan yerde basitçe geri okumaya kıyasla
hiçbir fayda sağlamadan çok fazla kodu etkiler.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TenantContext:
    """Varsa, mevcut isteğin JWT'sinden çözümlenen kiracı kimliği.

    Attributes:
        company_id: Çağıranın şirketi, ya da bir ``UserRole.ROOT`` öznesi
            için ``None`` (hiç şirketi yoktur -- bkz. ``UserModel.company_id``'nin
            docstring'i) ya da geçerli bir token hiç yoksa.
        is_root: Çağıranın JWT ``role`` iddiasının ``"root"`` olup olmadığı
            -- ``0013_rls`` göçünde eklenen RLS politikalarının
            ``company_id`` karşılaştırmalarına OR ile eklediği
            ``app.is_root`` Postgres GUC'unu yönlendirir; böylece kapsam
            belirlemiş bir root öznesi şirketler arasına geçebilir.
    """

    company_id: Optional[str]
    is_root: bool


current_tenant_var: ContextVar[Optional[TenantContext]] = ContextVar("current_tenant", default=None)


def get_current_tenant() -> Optional[TenantContext]:
    """Mevcut isteğin çözümlenmiş kiracı bağlamı, ya da ``None``.

    ``None`` hem "işlemde hiçbir istek yok" hem de "geçerli bir JWT'si
    olmayan bir istek" (anonim bir çağrı, ya da token'ı çözümlenemeyen bir
    istek) durumlarını kapsar -- bugün bu farkı önemseyen çağıranlar yok,
    çünkü her okuyucu (``app.infrastructure.database.session.get_db``)
    ikisine de aynı şekilde davranır: şirket yok, root atlaması yok, gerçek
    bir kimlik kurulana kadar RLS her kiracı-kapsamlı tabloda sıfır satır
    döner.
    """
    return current_tenant_var.get()
