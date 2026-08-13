"""Enable Postgres Row-Level Security: the kachow_app app role and tenant_isolation policies.

**Read this before touching this migration.** The single most likely way to
ship "RLS" that defends nothing: the connection making requests is the
table owner (or a superuser), and Postgres row-level security *never
applies to a table's owner*, `ENABLE ROW LEVEL SECURITY` or not -- see
https://www.postgresql.org/docs/current/ddl-rowsecurity.html. The backend
has connected as `postgres` (this database's owner, created by
`POSTGRES_USER`) since the project's very first migration; simply adding
`ENABLE ROW LEVEL SECURITY` here without also splitting the connection role
would be pure theater, "protecting" nothing while looking done.

This migration therefore does two things that must both hold, together:

1. Creates `kachow_app`: `NOSUPERUSER`, no table ownership, plain DML grants
   (`SELECT`/`INSERT`/`UPDATE`/`DELETE`) on every table -- see
   `app.core.config.Settings.DATABASE_URL`'s docstring, which the app's
   runtime connection switches to as of this change (`compose.yml`).
   Idempotent (`DO $$ ... IF NOT EXISTS ...`): a database whose Postgres
   volume predates this migration never re-runs `scripts/init-db.sh` (only
   a *fresh* volume's init hook does), so this is the only place guaranteed
   to run against every existing deployment.
2. `ENABLE` + `FORCE ROW LEVEL SECURITY` and a `tenant_isolation` policy on
   the tables Faz 1 already made `company_id NOT NULL` on: `users`, `units`,
   `documents`, `invited_emails`, plus `permission_grants` (NOT NULL since
   Faz 2). `FORCE` matters as much as `ENABLE` does: without it, RLS is
   skipped for the table's owner *and* for any role with the `BYPASSRLS`
   attribute -- `kachow_app` has neither, so this is redundant defense here,
   but `FORCE` is what makes the policy apply unconditionally to every
   non-owner role, present and future, rather than something the next
   person to create a role has to remember to preserve.

The policy: `company_id = current_setting('app.current_company_id', true) OR
current_setting('app.is_root', true) = 'on'`. `current_setting(key, true)`
(the `true` = "missing_ok") returns NULL when unset rather than raising --
`company_id = NULL` is NULL, not TRUE, in SQL's three-valued logic, so a
session that never set the GUC at all (forgot to, or is a stray raw-SQL/
analytics connection) sees zero rows on every RLS'd table by default: the
same fail-secure shape `app.core.permissions.role_checker.clearance_for`
already documents for "unknown clearance clears nothing". `company_id` stays
a plain `String` (this repo's uuid-as-string convention, see `CompanyModel.
id`), so no `::uuid` cast is needed on either side of the comparison --
casting a NULL setting would raise on some Postgres versions instead of
comparing false, which is not the behaviour wanted here anyway.

One `CREATE POLICY` per table (not two OR'd policies, as an earlier version
of the tenancy plan sketched) -- functionally identical: Postgres already
OR's multiple PERMISSIVE policies on the same table together, so folding the
root bypass into one `USING`/`WITH CHECK` expression is simpler to read and
maintain without changing the semantics.

**What this migration deliberately does NOT do**: it does not touch
`drafts`, `chat_sessions`, `chat_messages`, `runs`, `run_steps`, or
`guardrail_events` -- their `company_id` is still nullable (see
`RunModel.company_id`'s docstring; populating it needs threading `company_id`
through LangGraph state, a separate piece of work). Enabling RLS on a table
whose `company_id` is routinely NULL for legitimate rows would make those
rows invisible to everyone but a scoped-in root, which is a functional
regression, not hardening -- RLS lands on a table only once the column
backing its policy is actually populated on every row.

**Alembic itself, and the narrow pre-tenant identity-lookup paths (login,
refresh, registration)**, keep using the schema-owner connection
(`ALEMBIC_DATABASE_URL`/`get_owner_db`) precisely because they must -- see
those settings'/that function's own docstrings. `kachow_app` is for
everything else.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-13

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from app.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_APP_ROLE = "kachow_app"

#: Tables where company_id is already NOT NULL (Faz 1: users/units/documents/
#: invited_emails; Faz 2: permission_grants) -- see this module's own
#: docstring for why every other tenant-shaped table is excluded for now.
_RLS_TABLES = ("users", "units", "documents", "invited_emails", "permission_grants")


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. The restricted app role -- idempotent, see this module's docstring.
    #
    # The password is inlined as a plain SQL string literal (single quotes
    # doubled, standard SQL escaping), not passed as a SQLAlchemy bind
    # parameter: a `DO $$ ... $$` block's body is lexed as one opaque
    # dollar-quoted string *before* the outer parser would otherwise
    # recognise a driver placeholder inside it, so a `:password`-style bind
    # would never actually be substituted there -- it would reach Postgres
    # as the literal, un-substituted placeholder text. Safe here because the
    # value is a trusted config default (see `settings.KACHOW_APP_DB_PASSWORD`'s
    # docstring), not attacker input, and the only character that needs
    # escaping for a single-quoted SQL literal is the quote itself.
    # ------------------------------------------------------------------
    password_literal = settings.KACHOW_APP_DB_PASSWORD.replace("'", "''")
    bind.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                    CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{password_literal}'
                        NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
                END IF;
            END
            $$;
            """
        )
    )

    bind.execute(text(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE};"))
    bind.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE};"))
    bind.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE};"))
    # CURRENT_USER here is whichever role this migration itself is running
    # as -- always the schema owner (ALEMBIC_DATABASE_URL), since that's the
    # only connection with DDL rights to run a migration at all. This makes
    # every table a *future* migration creates (also owned by that same
    # role) automatically grant kachow_app the same DML rights, with no
    # separate "don't forget to grant the new table" step to remember.
    bind.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE};"
        )
    )
    bind.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {_APP_ROLE};"
        )
    )

    # ------------------------------------------------------------------
    # 2. Row-level security itself.
    # ------------------------------------------------------------------
    for table in _RLS_TABLES:
        bind.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;"))
        bind.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"))
        bind.execute(
            text(
                f"""
                CREATE POLICY tenant_isolation ON {table}
                  USING (
                    company_id = current_setting('app.current_company_id', true)
                    OR current_setting('app.is_root', true) = 'on'
                  )
                  WITH CHECK (
                    company_id = current_setting('app.current_company_id', true)
                    OR current_setting('app.is_root', true) = 'on'
                  );
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    for table in reversed(_RLS_TABLES):
        bind.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table};"))
        bind.execute(text(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;"))
        bind.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;"))

    bind.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public "
            f"REVOKE USAGE, SELECT ON SEQUENCES FROM {_APP_ROLE};"
        )
    )
    bind.execute(
        text(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA public "
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_APP_ROLE};"
        )
    )
    bind.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE};"))
    bind.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE};"))
    bind.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE};"))
    # Deliberately does not DROP ROLE kachow_app: the running app may still
    # hold live connections under it (a downgrade does not imply the app has
    # been stopped first), and an unused role with no privileges left is
    # harmless to leave behind -- same call 0010_backfill_tenancy makes for
    # its own "legacy" company/user rows on downgrade.
