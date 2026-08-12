"""Best-effort bootstrap of the default routable units.

Mirrors `app.domains.users.seeder.seed_default_users`: a fresh deployment
otherwise starts with an empty `units` table, and an empty table means every
routing decision short-circuits to "no unit, needs human approval" (see
`app.ai.workflows.routing_graph`) until an admin manually creates units
through `POST /units`. Seeding the units the system shipped with before this
domain existed keeps behaviour unchanged on a fresh environment.

Idempotent by design: each unit is checked by name before it is created, so
re-running this on every startup never duplicates a row. Each unit gets its
own short-lived session, same reasoning as the users seeder -- one
conflicting name must not block the others from being seeded.

Every function swallows its own exceptions and only logs -- seeding must
never be the reason the API fails to boot.
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

from app.core.config import settings
from app.domains.units.model.unit_model import UnitModel
from app.domains.units.repository import UnitRepository
from app.infrastructure.database.session import AsyncSessionLocal

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


async def _seed_one(unit: _SeedUnit) -> bool:
    """Create one unit if it doesn't already exist.

    Returns:
        True if a new row was created, False if a unit with that name
        already existed and nothing was done.
    """
    async with AsyncSessionLocal() as session:
        repository = UnitRepository(session)
        if await repository.get_by_name(unit.name) is not None:
            return False

        await repository.create(
            UnitModel(
                id=str(uuid4()),
                name=unit.name,
                description=unit.description,
                is_active=True,
            )
        )
        await session.commit()
        return True


async def seed_default_units() -> None:
    """Create the default routable units, skipping any that already exist.

    A no-op when `settings.SEED_DEFAULT_UNITS` is off. Safe to call on every
    startup.
    """
    if not settings.SEED_DEFAULT_UNITS:
        return

    created = []
    for unit in _seed_units():
        try:
            if await _seed_one(unit):
                created.append(unit.name)
        except Exception:
            logger.exception("Failed to seed default unit %s", unit.name)

    if created:
        logger.info("Seeded default units: %s", ", ".join(created))
