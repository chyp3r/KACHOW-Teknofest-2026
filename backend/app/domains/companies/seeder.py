"""Bir demo şirketin en iyi çaba (best-effort) ile önyüklenmesi (bootstrap).

Seed edilen diğer her satır (root hariç) bağlanacağı bir `company_id`'ye
ihtiyaç duyar -- `app.domains.users.seeder` ve `app.domains.units.seeder`
ikisi de bunun önce çalışmasına bağımlıdır (bkz. `app.lifespan`'in seed
sırası). `app.domains.units.seeder` ile aynı kural gereği slug'a göre
idempotenttir.

Kendi istisnalarını yutar ve yalnızca loglar -- seeding hiçbir zaman
API'nin ayağa kalkamamasının nedeni olmamalıdır.
"""

import logging
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.domains.companies import provider as company_provider
from app.domains.companies.model.company_model import CompanyModel
from app.domains.companies.repository import CompanyRepository
from app.infrastructure.database.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def seed_demo_company() -> Optional[str]:
    """Demo şirket henüz yoksa oluşturur.

    `settings.SEED_DEMO_COMPANY` kapalı ama şirket önceki bir çalıştırmadan
    zaten mevcutsa hiçbir şey yapmaz (mevcut id'yi döndürür) -- alt akıştaki
    çağıranların (kullanıcı/birim seeder'ları) her halükarda id'ye ihtiyacı
    vardır.

    Returns:
        Demo şirketin id'si, ya da seeding kapalıysa ve henüz demo şirket
        yoksa `None`.
    """
    async with AsyncSessionLocal() as session:
        repository = CompanyRepository(session)
        existing = await repository.get_by_slug(settings.SEED_DEMO_COMPANY_SLUG)
        if existing is not None:
            return existing.id

        if not settings.SEED_DEMO_COMPANY:
            return None

        try:
            company = CompanyModel(
                id=str(uuid4()),
                name=settings.SEED_DEMO_COMPANY_NAME,
                slug=settings.SEED_DEMO_COMPANY_SLUG,
                is_active=True,
                is_deleted=False,
                settings={},
                created_by=None,
            )
            await repository.create(company)
            await session.commit()
            logger.info("Seeded demo company '%s' (%s)", company.name, company.id)
            # Bu olmadan, `app.domains.companies.provider._read_profile_
            # from_db` demo şirket için okuyacağı yapılandırılmış bir
            # `company_profile` bulamıyor ve ham `CompanyModel.name`'e geri
            # düşüyordu -- başka bir yerde *sentetik* bir şirketin adının
            # "bilinen bilgi" olarak kendinden emin bir gerçek gibi sızmasına
            # yol açan aynı geri düşme (fallback) mekanizması. Demo ortamı,
            # bu fallback'e kazara güvenmek yerine, gerçekten yapılandırılmış
            # bir profili kullanmalıdır.
            try:
                await company_provider.set_company_profile(
                    company.id,
                    display_name=settings.SEED_DEMO_COMPANY_NAME,
                    short_name=settings.SEED_DEMO_COMPANY_NAME,
                )
            except Exception:
                logger.exception("Failed to seed demo company's profile")
            return company.id
        except Exception:
            logger.exception("Failed to seed demo company")
            return None

