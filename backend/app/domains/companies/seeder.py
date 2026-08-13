"""Best-effort bootstrap of one demo company.

Every other seeded row (root aside) needs a `company_id` to anchor to --
`app.domains.users.seeder` and `app.domains.units.seeder` both depend on this
running first (see `app.lifespan`'s seeding order). Idempotent by slug, same
convention as `app.domains.units.seeder`.

Swallows its own exceptions and only logs -- seeding must never be the
reason the API fails to boot.
"""

import logging
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.domains.companies.model.company_model import CompanyModel
from app.domains.companies.repository import CompanyRepository
from app.infrastructure.database.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def seed_demo_company() -> Optional[str]:
    """Create the demo company if it doesn't already exist.

    A no-op (returns the existing id) when `settings.SEED_DEMO_COMPANY` is
    off but the company already exists from a prior run -- callers
    downstream (the user/unit seeders) still need the id either way.

    Returns:
        The demo company's id, or `None` if seeding is off and no demo
        company exists yet.
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
            return company.id
        except Exception:
            logger.exception("Failed to seed demo company")
            return None
