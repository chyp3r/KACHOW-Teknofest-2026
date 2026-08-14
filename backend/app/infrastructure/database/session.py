import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.context import get_current_tenant

logger = logging.getLogger(__name__)

# Create async engine for PostgreSQL connection -- the app's restricted,
# non-owner role from Faz 3 (Postgres RLS) onward. See settings.DATABASE_URL's
# own docstring for why this must not be a table-owning/superuser connection.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for debug SQL query logging
    future=True,
    pool_pre_ping=True,  # Test connections before using
)

# Async session maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

#: The schema-owner connection -- see settings.ALEMBIC_DATABASE_URL's
#: docstring. Used only by get_owner_db below, for the narrow set of
#: pre-tenant identity lookups that must bypass row-level security by
#: necessity (see that function's own docstring), never as a general escape
#: hatch.
owner_engine = create_async_engine(
    settings.effective_alembic_database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
)

OwnerAsyncSessionLocal = async_sessionmaker(
    bind=owner_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def _apply_tenant_guc(session: AsyncSession, company_id: Optional[str], is_root: bool) -> None:
    """Set the Postgres GUCs the RLS policies (migration 0013_rls) key off of.

    Must be the *first* statement run on ``session``. ``AsyncSession`` begins
    its transaction lazily, on first use, and ``set_config(..., true)`` (==
    ``SET LOCAL``) only lasts for the transaction it's issued in -- calling
    this before the caller runs anything else makes it the statement that
    begins the transaction, so the setting survives for every later
    statement on this session, right up to the final commit/rollback.
    Calling it any later would let an earlier, GUC-less statement start (and
    on the request path, possibly finish) its own transaction first, and the
    setting would evaporate the moment that one committed.

    Args:
        session: A freshly opened session, nothing executed on it yet.
        company_id: Scopes ``app.current_company_id``. ``None``/falsy
            becomes the empty string, which matches no real row's
            ``company_id`` (all NOT NULL, non-empty) -- the fail-secure
            "no tenant identified" state.
        is_root: Sets ``app.is_root``, which the RLS policies OR into their
            ``company_id`` comparison so a scoped-in root subject can read
            across companies.
    """
    await session.execute(
        text("SELECT set_config('app.current_company_id', :cid, true)"),
        {"cid": company_id or ""},
    )
    await session.execute(
        text("SELECT set_config('app.is_root', :v, true)"),
        {"v": "on" if is_root else "off"},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an asynchronous SQLAlchemy database session.

    Applies the current request's tenant GUCs (see ``_apply_tenant_guc``)
    before yielding -- resolved from ``app.core.context.get_current_tenant``,
    which ``app.api.middleware.tenant.TenantContextMiddleware`` populates
    from the request's JWT before any dependency runs. No tenant context (an
    anonymous request, or one whose auth dependency hasn't rejected it yet)
    resolves to an empty company scope and ``is_root=False``: row-level
    security then returns zero rows on every RLS'd table, the fail-secure
    default -- the same shape ``app.core.permissions.role_checker.
    clearance_for`` already documents for "unknown clearance clears nothing".

    Cleans up resources and rolls back on failure automatically.
    """
    async with AsyncSessionLocal() as session:
        try:
            tenant = get_current_tenant()
            await _apply_tenant_guc(
                session,
                tenant.company_id if tenant else None,
                tenant.is_root if tenant else False,
            )
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error: {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_owner_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session on the schema-owner connection.

    For the narrow set of pre-tenant identity lookups that must search
    ``users``/``invited_emails`` by a globally-unique ``username``/``email``
    *before* any company context exists to scope a row-level-security policy
    by: ``POST /auth/login``, ``POST /auth/refresh``, ``POST /users``
    (invite-gated registration). See ``settings.ALEMBIC_DATABASE_URL``'s
    docstring.

    Deliberately bypasses row-level security entirely -- the owner
    connection always can, regardless of any policy (see migration
    ``0013_rls``'s own module docstring on why the app's normal connection
    must NOT be able to do this). Safe here *only* because every query these
    three routes run is inherently cross-tenant by definition -- a
    username/email is unique system-wide, not per company -- never because
    the caller is trusted with anything more than that. Every other route
    continues to use ``get_db``.
    """
    async with OwnerAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error (owner connection): {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def tenant_session(
    company_id: Optional[str], is_root: bool = False
) -> AsyncGenerator[AsyncSession, None]:
    """A ``get_db``-equivalent session for code with no request to read tenant context from.

    For out-of-request writers/readers that already know which company
    they're acting for: ``app.domains.units.provider.
    get_active_units_for_routing``, the users/units seeders
    (``app.domains.users.seeder``, ``app.domains.units.seeder``), the four
    best-effort recorders (``app.domains.drafts.draft_recorder``,
    ``app.observability.run_recorder``/``guardrail_recorder``,
    ``app.domains.chat.chat_recorder`` -- since migration ``0016_recorder_
    tables_rls``, see ``RunModel.company_id``'s docstring), and
    ``app.events.subscribers``' notification-writing listeners. Applies the
    same GUCs ``get_db`` does (see ``_apply_tenant_guc``), from explicit
    arguments instead of ``app.core.context.get_current_tenant`` -- there is
    no request in flight to have populated it.
    """
    async with AsyncSessionLocal() as session:
        try:
            await _apply_tenant_guc(session, company_id, is_root)
            yield session
            await session.commit()
        except Exception as e:
            logger.error(
                f"Database transaction error (tenant_session): {e}. Rolling back.",
                exc_info=True,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


async def verify_db_connection() -> bool:
    """Verify that we can establish a connection to the PostgreSQL database."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            val = result.scalar()
            if val == 1:
                logger.info("PostgreSQL database connection verified successfully.")
                return True
            return False
    except Exception as e:
        logger.error(
            f"PostgreSQL database connection verification failed: {e}",
            exc_info=True,
        )
        return False
