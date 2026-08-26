"""Varsayılan yönlendirilebilir birimlerin best-effort önyükleme (bootstrap) işlemi.

`app.domains.users.seeder.seed_default_users`'ı yansıtır: aksi takdirde
taze bir dağıtım (deployment) boş bir `units` tablosuyla başlar ve boş bir
tablo, bir admin `POST /units` üzerinden manuel olarak birim oluşturana
kadar her yönlendirme kararının "birim yok, insan onayı gerekiyor"
durumuna kısa devre yapması demektir (bkz. `app.ai.workflows.routing_graph`).
Bu domain var olmadan önce sistemin geldiği birimleri seed etmek, taze bir
ortamda davranışı değiştirmeden korur.

Tasarım gereği idempotent: her birim oluşturulmadan önce adına göre
kontrol edilir, bu yüzden her başlatmada tekrar çalıştırmak asla bir
satırı çoğaltmaz. Her birim kendi kısa ömürlü oturumunu alır, users
seeder ile aynı gerekçe -- çakışan bir ad diğerlerinin seed edilmesini
engellememelidir.

Her fonksiyon kendi istisnalarını yutar ve sadece loglar -- seed işlemi
API'nin ayağa kalkmama sebebi olmamalıdır.
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

from app.core.config import settings
from app.domains.units.model.unit_model import UnitModel
from app.domains.units.repository import UnitRepository
from app.infrastructure.database.session import tenant_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SeedUnit:
    name: str
    description: str


def _seed_units() -> list[_SeedUnit]:
    return [
        _SeedUnit(
            "İnsan Kaynakları",
            "Personel işleri, atamalar, izinler, özlük hakları, staj ve insan kaynakları süreçleri.",
        ),
        _SeedUnit(
            "Hukuk Müşavirliği",
            "Yasal davalar, hukuki görüş talepleri, mevzuat yorumlama, sözleşmeler ve yasal ihtilaflar.",
        ),
        _SeedUnit(
            "Mali İşler",
            "Ödemeler, bütçe, faturalar, maaşlar ve finansal işlemler.",
        ),
        _SeedUnit(
            "Vatandaş İlişkileri",
            "Vatandaş şikayetleri, bilgi edinme başvuruları, dilekçeler ve halkla ilişkiler.",
        ),
        _SeedUnit(
            "Bilgi İşlem Dairesi",
            "Bilgi teknolojileri, teknik altyapı, yazılım, donanım ve siber güvenlik talepleri.",
        ),
        _SeedUnit(
            "Destek Hizmetleri",
            "Temizlik, taşıma, yemek, güvenlik, bina bakım/onarım ve genel idari destek hizmetleri.",
        ),
    ]


async def _seed_one(unit: _SeedUnit, company_id: str) -> bool:
    """`company_id` için, henüz yoksa bir birim oluşturur.

    Returns:
        Yeni bir satır oluşturulduysa True; o isimde bir birim zaten
        varsa ve hiçbir şey yapılmadıysa False.
    """
    async with tenant_session(company_id) as session:
        repository = UnitRepository(session)
        if await repository.get_by_name(unit.name, company_id) is not None:
            return False

        await repository.create(
            UnitModel(
                id=str(uuid4()),
                company_id=company_id,
                name=unit.name,
                description=unit.description,
                is_active=True,
            )
        )
        await session.commit()
        return True


async def seed_default_units(company_id: str) -> None:
    """`company_id` için varsayılan yönlendirilebilir birimleri oluşturur,
    zaten var olanları atlar.

    `settings.SEED_DEFAULT_UNITS` kapalıyken hiçbir şey yapmaz. Her
    başlatmada çağrılması güvenlidir.

    Args:
        company_id: Birimlerin seed edileceği şirket -- birimler şirket
            kapsamlıdır, bu yüzden bu, varsayılan seti isteyen her şirket
            için bir kez çalışmalıdır (bugün sadece demo şirket; bkz.
            `app.domains.companies.seeder`).
    """
    if not settings.SEED_DEFAULT_UNITS:
        return

    created = []
    for unit in _seed_units():
        try:
            if await _seed_one(unit, company_id):
                created.append(unit.name)
        except Exception:
            logger.exception("Failed to seed default unit %s", unit.name)

    if created:
        logger.info("Seeded default units for company %s: %s", company_id, ", ".join(created))
