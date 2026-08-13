#!/bin/bash
set -e

# Runs once, only against a genuinely fresh Postgres volume (Postgres's own
# docker-entrypoint-initdb.d convention) -- an existing volume never re-runs
# this, which is exactly why migration 0013_rls does the same kachow_app
# role/grant setup again, idempotently, for databases that predate this
# script's RLS-related additions. See that migration's own module docstring
# for the full reasoning (role separation, ALTER DEFAULT PRIVILEGES, why
# FORCE ROW LEVEL SECURITY matters).
#
# No tables exist yet at this point (Alembic runs after this script, via
# `make bootstrap`) -- the plain GRANT on existing tables is therefore a
# no-op here; ALTER DEFAULT PRIVILEGES is what actually matters, since it
# applies to every table $POSTGRES_USER creates from this point on,
# including all of Alembic's migrations.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE langfuse' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec

    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'kachow_app') THEN
            CREATE ROLE kachow_app LOGIN PASSWORD '${KACHOW_APP_DB_PASSWORD:-kachow_app_dev_only}'
                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
        END IF;
    END
    \$\$;

    GRANT USAGE ON SCHEMA public TO kachow_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kachow_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kachow_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO kachow_app;
    ALTER DEFAULT PRIVILEGES FOR ROLE "$POSTGRES_USER" IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO kachow_app;
EOSQL
