"""The single most important check in this package.

Row-level security is a complete no-op for a table's owner (or any
``BYPASSRLS`` role) -- `ENABLE ROW LEVEL SECURITY` does not change that. The
most likely way to ship "RLS" that defends nothing at all is for the app's
runtime connection to still be that owner, in which case every other test in
this package would pass for entirely the wrong reason: not because Postgres
is enforcing the policy, but because nothing was ever really trying to break
it. See migration ``0013_rls``'s own module docstring for the full
reasoning this test exists to catch.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

_RLS_TABLES = ("users", "units", "documents", "invited_emails", "permission_grants")


async def test_kachow_app_is_not_the_schema_owner(app_engine, owner_engine):
    """`kachow_app` must be a distinct role from whatever owns these tables."""
    async with app_engine.connect() as conn:
        app_role = (await conn.execute(text("SELECT current_user"))).scalar_one()

    assert app_role == "kachow_app"

    async with owner_engine.connect() as conn:
        table_owner = (
            await conn.execute(text("SELECT tableowner FROM pg_tables WHERE tablename = 'documents'"))
        ).scalar_one()

    assert table_owner != app_role


async def test_kachow_app_has_no_superuser_or_bypassrls_attribute(owner_engine):
    """Either attribute alone would make every RLS policy below a no-op for this role."""
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'kachow_app'")
            )
        ).one()

    rolsuper, rolbypassrls = row
    assert rolsuper is False
    assert rolbypassrls is False


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_row_level_security_is_actually_enabled_and_forced(owner_engine, table):
    """`ENABLE` alone is not enough -- without `FORCE`, RLS is skipped for the owner
    *and* for any future `BYPASSRLS` role, silently narrowing who it protects against."""
    async with owner_engine.connect() as conn:
        relrowsecurity, relforcerowsecurity = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :t"
                ),
                {"t": table},
            )
        ).one()

    assert relrowsecurity is True, f"{table}: ROW LEVEL SECURITY is not enabled"
    assert relforcerowsecurity is True, f"{table}: ROW LEVEL SECURITY is not FORCEd"


@pytest.mark.parametrize("table", _RLS_TABLES)
async def test_tenant_isolation_policy_exists(owner_engine, table):
    async with owner_engine.connect() as conn:
        policy_count = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_policies WHERE tablename = :t AND policyname = 'tenant_isolation'"
                ),
                {"t": table},
            )
        ).scalar_one()

    assert policy_count == 1


async def test_owner_connection_bypasses_rls_by_definition(owner_engine, two_companies):
    """Sanity check on the fixtures themselves: the owner engine used to set up
    `two_companies` must see rows from *both* companies with no GUC set at all --
    this is what "owner" means, and every other test in this package relies on it
    being true for setup while asserting the opposite for `app_engine`."""
    async with owner_engine.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM companies WHERE id IN (:a, :b)"),
                {"a": two_companies["a"]["company_id"], "b": two_companies["b"]["company_id"]},
            )
        ).scalar_one()

    assert count == 2
