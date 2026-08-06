"""Best-effort bootstrap of one ADMIN, one MANAGER and one EMPLOYEE account.

A fresh deployment (a new environment, a demo, CI) otherwise has no users at
all -- the only way to create one is the invite-gated registration flow
(`UserService.register_user`), which needs an existing account to issue the
invite in the first place. This creates one account per role directly
through `UserRepository`, bypassing that gate entirely (a bootstrap has
nothing to invite itself with).

Idempotent by design: each account is checked by email (and by username, to
avoid an IntegrityError if that username was independently taken by a
different email) before it is created, so re-running this on every startup
never duplicates or overwrites an existing row. Each account gets its own
short-lived session -- mirrors `app.observability.run_recorder`'s pattern,
since `app.lifespan` has no request-scoped `Depends(get_db)` -- so one
account's conflict never blocks the other two from being seeded.

Every function swallows its own exceptions and only logs -- seeding must
never be the reason the API fails to boot.
"""

import logging
from dataclasses import dataclass
from uuid import uuid4

from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.core.security import hash_password
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SeedAccount:
    username: str
    email: str
    password: str
    role: str


def _seed_accounts() -> list[_SeedAccount]:
    return [
        _SeedAccount(
            username="admin",
            email=settings.SEED_ADMIN_EMAIL,
            password=settings.SEED_ADMIN_PASSWORD,
            role=UserRole.ADMIN.value,
        ),
        _SeedAccount(
            username="manager",
            email=settings.SEED_MANAGER_EMAIL,
            password=settings.SEED_MANAGER_PASSWORD,
            role=UserRole.MANAGER.value,
        ),
        _SeedAccount(
            username="employee",
            email=settings.SEED_EMPLOYEE_EMAIL,
            password=settings.SEED_EMPLOYEE_PASSWORD,
            role=UserRole.EMPLOYEE.value,
        ),
    ]


async def _seed_one(account: _SeedAccount) -> bool:
    """Create one account if it doesn't already exist.

    Returns:
        True if a new row was created, False if it already existed (by
        email or by username) and nothing was done.
    """
    async with AsyncSessionLocal() as session:
        repository = UserRepository(session)
        if await repository.get_by_email(account.email) is not None:
            return False
        if await repository.get_by_username(account.username) is not None:
            logger.warning(
                "Seed account username '%s' is already taken by a different "
                "email; skipping.",
                account.username,
            )
            return False

        user = UserModel(
            id=str(uuid4()),
            username=account.username,
            email=account.email,
            hashed_password=hash_password(account.password),
            role=account.role,
            is_active=True,
            is_deleted=False,
        )
        await repository.create(user)
        await session.commit()
        return True


async def seed_default_users() -> None:
    """Create the default ADMIN/MANAGER/EMPLOYEE accounts, skipping any that
    already exist.

    A no-op when `settings.SEED_DEFAULT_USERS` is off. Safe to call on every
    startup.
    """
    if not settings.SEED_DEFAULT_USERS:
        return

    created = []
    for account in _seed_accounts():
        try:
            if await _seed_one(account):
                created.append(f"{account.email} ({account.role})")
        except Exception:
            logger.exception("Failed to seed default account %s", account.email)

    if created:
        logger.info("Seeded default accounts: %s", ", ".join(created))
