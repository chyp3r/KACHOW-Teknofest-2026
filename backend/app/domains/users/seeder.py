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
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.enums.user_role import UserRole
from app.core.security import hash_password
from app.domains.users.model.user_model import UserModel
from app.domains.users.repository import UserRepository
from app.infrastructure.database.session import OwnerAsyncSessionLocal, tenant_session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SeedAccount:
    username: str
    email: str
    password: str
    role: str
    #: None only for root -- see UserModel.company_id's CHECK constraint.
    company_id: Optional[str]


def _seed_accounts(company_id: Optional[str]) -> list[_SeedAccount]:
    accounts = [
        _SeedAccount(
            username="root",
            email=settings.SEED_ROOT_EMAIL,
            password=settings.SEED_ROOT_PASSWORD,
            role=UserRole.ROOT.value,
            company_id=None,
        ),
    ]
    if company_id is not None:
        accounts.extend(
            [
                _SeedAccount(
                    username="admin",
                    email=settings.SEED_ADMIN_EMAIL,
                    password=settings.SEED_ADMIN_PASSWORD,
                    role=UserRole.ADMIN.value,
                    company_id=company_id,
                ),
                _SeedAccount(
                    username="manager",
                    email=settings.SEED_MANAGER_EMAIL,
                    password=settings.SEED_MANAGER_PASSWORD,
                    role=UserRole.MANAGER.value,
                    company_id=company_id,
                ),
                _SeedAccount(
                    username="employee",
                    email=settings.SEED_EMPLOYEE_EMAIL,
                    password=settings.SEED_EMPLOYEE_PASSWORD,
                    role=UserRole.EMPLOYEE.value,
                    company_id=company_id,
                ),
            ]
        )
    return accounts


async def _seed_one(account: _SeedAccount) -> bool:
    """Create one account if it doesn't already exist.

    The existence check runs on the schema-owner connection
    (`OwnerAsyncSessionLocal`), not a tenant-scoped one: `username`/`email`
    are unique *system-wide* (`UserModel`'s own `unique=True` columns), not
    per company, so "does this already exist" has to see every company, the
    same reasoning as `app.infrastructure.database.session.get_owner_db`.
    Checking it under a single company's row-level-security scope instead
    was tried first and broke exactly this way: two different companies can
    each be seeded with a user named "admin", the per-company-scoped check
    can't see the other one, and the insert then fails on the *global*
    unique constraint anyway -- just later, and as an unhandled
    `IntegrityError` instead of a clean "already exists, skip".

    The insert itself does use `tenant_session` -- `users` is under
    row-level security (migration `0013_rls`) and this write has no request
    to read a tenant `ContextVar` from, so it must supply the target
    company_id (or `is_root=True` for the root account, which has none)
    explicitly.

    Returns:
        True if a new row was created, False if it already existed (by
        email or by username) and nothing was done.
    """
    async with OwnerAsyncSessionLocal() as check_session:
        check_repository = UserRepository(check_session)
        if await check_repository.get_by_email(account.email) is not None:
            return False
        if await check_repository.get_by_username(account.username) is not None:
            logger.warning(
                "Seed account username '%s' is already taken by a different "
                "email; skipping.",
                account.username,
            )
            return False

    is_root = account.role == UserRole.ROOT.value
    async with tenant_session(account.company_id, is_root=is_root) as session:
        repository = UserRepository(session)
        user = UserModel(
            id=str(uuid4()),
            company_id=account.company_id,
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


async def seed_default_users(company_id: Optional[str]) -> None:
    """Create the default ROOT/ADMIN/MANAGER/EMPLOYEE accounts, skipping any
    that already exist.

    A no-op when `settings.SEED_DEFAULT_USERS` is off. Safe to call on every
    startup.

    Args:
        company_id: The demo company to bind ADMIN/MANAGER/EMPLOYEE to (see
            `app.domains.companies.seeder.seed_demo_company`, which must run
            first). ROOT is seeded regardless, since it has no company.
            When `None` (demo company seeding is off and none exists yet),
            only ROOT is seeded.
    """
    if not settings.SEED_DEFAULT_USERS:
        return

    created = []
    for account in _seed_accounts(company_id):
        try:
            if await _seed_one(account):
                created.append(f"{account.email} ({account.role})")
        except Exception:
            logger.exception("Failed to seed default account %s", account.email)

    if created:
        logger.info("Seeded default accounts: %s", ", ".join(created))
