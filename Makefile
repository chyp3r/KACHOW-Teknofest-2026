.PHONY: setup-db bootstrap up down logs test eval eval-baseline eval-llm \
	migrate seed shell psql restart-backend \
	reset-db reset-checkpoints reset-cache reset-storage reset-document-qa reset

setup-db:
	docker compose exec db psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'langfuse'" | grep -q 1 || docker compose exec db psql -U postgres -c "CREATE DATABASE langfuse"

# Brings the system up from a completely empty state (no containers, no
# volumes, no schema) to a ready-to-use one in a single command: builds and
# starts the datastores, waits for Postgres to actually accept connections
# (compose.yml declares no healthcheck, so `up -d` returns long before
# Postgres is ready -- running migrations against it immediately would
# race), creates the langfuse database (setup-db), runs every Alembic
# migration, then starts the backend. The backend's own lifespan hook
# (backend/app/lifespan.py) seeds the default admin/manager/employee
# accounts on that same boot -- see backend/app/core/config.py's SEED_*
# settings for the credentials. Every step here is idempotent
# (`docker compose up`, `alembic upgrade head`, and the seeder all no-op on
# what already exists), so this is also safe to re-run on an
# already-running system, e.g. after pulling migrations someone else wrote.
#
# Deliberately doesn't build/start `frontend` -- deploy/docker/
# frontend.Dockerfile hardcodes the x64 Rollup native binary
# (@rollup/rollup-linux-x64-musl) and fails to build on an arm64 host
# (Apple Silicon); that's a pre-existing bug independent of this target,
# tracked separately. Run `make up` for the full stack including frontend
# on an x64 host, or `cd frontend && npm run dev` locally in the meantime.
bootstrap:
	docker compose up -d --build db redis qdrant
	@echo "Waiting for Postgres to accept connections..."
	@until docker compose exec -T db pg_isready -U $${POSTGRES_USER:-postgres} > /dev/null 2>&1; do sleep 1; done
	$(MAKE) setup-db
	docker compose run --rm --no-deps backend alembic upgrade head
	docker compose up -d --build backend
	@echo "Bootstrap complete: backend on http://localhost:8000."
	@echo "Default accounts were seeded automatically (see SEED_* in backend/app/core/config.py)."

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Applies any migration written since the system was last bootstrapped,
# without the rest of `bootstrap`'s from-empty dance (no build, no wait
# loop, no backend restart). The everyday "I pulled someone else's
# migration" command.
migrate:
	docker compose run --rm --no-deps backend alembic upgrade head

# Re-runs the same seeding chain backend/app/lifespan.py runs on every
# boot (demo company -> users -> units, all idempotent), without
# restarting the running backend container -- see scripts/seed_users.py's
# own docstring for why this is `run --rm`, not `exec`. Useful right after
# `migrate` against a database that had rows before this system's tables
# existed, or any time `reset` below is run against a backend you don't
# want to bounce.
seed:
	docker compose run --rm backend python scripts/seed_users.py

# Convenience shells for poking at a running stack.
shell:
	docker compose exec backend bash

psql:
	docker compose exec db psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-kachow}

restart-backend:
	docker compose restart backend

# Runs with the compose services up. Redis used to be load-bearing here: seven
# API tests failed without it, because rate_limit() sits in front of the document
# endpoints and turned a cache outage into a 500. That was the limiter failing
# closed, not a test-environment requirement -- it now fails open, and the suite
# passes with Redis reachable or unreachable alike. Postgres and Qdrant are still
# genuinely needed by the integration tests.
test:
	docker compose run --rm backend pytest -q

# Deterministic evaluation of the non-LLM decision layer. Deliberately a
# separate target rather than a test: the full run is a measurement, not a
# pass/fail gate, and it must not be bound by pytest's 60s per-test timeout.
# --no-deps is correct *here*: the suites call pure decision functions and
# touch no infrastructure at all. Verified by the run itself -- if that ever
# stops being true it fails loudly rather than silently degrading.
eval:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite all

# Records the pre-change numbers every later run is compared against.
# Compare with: make eval ARGS="--baseline evaluation/reports/all-baseline.json"
eval-baseline:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite all --label baseline

# Opt-in, not part of `make eval`: makes real Ollama calls for every intent
# case the fusion layer leaves contested (see evaluation/harness/
# intent_suite.py::run_with_model), so it is slower and its model-sourced
# decisions are not perfectly reproducible run to run the way the rest of the
# suite is. --no-deps is still correct here -- Ollama is reached over
# host.docker.internal regardless of which compose services are up, the same
# way the backend service's own OLLAMA_BASE_URL is wired.
eval-llm:
	docker compose run --rm --no-deps backend python -m evaluation.generate_report --suite intents --with-model --label with-model

# ---------------------------------------------------------------------------
# Reset: wipes application data (companies/users/documents/drafts/chat/...)
# and reseeds a clean system, without touching the mevzuat/örnek-yazışma
# Qdrant collections -- those are populated by separate, expensive indexing
# scripts (scripts/index_mevzuat.py, scripts/index_yazisma_examples.py), not
# by anything below. Each target is independently runnable for a narrower
# cleanup; `reset` runs all of them in the right order and reseeds at the end.
# ---------------------------------------------------------------------------

# Drops and recreates every Alembic-managed table by replaying the full
# migration history -- every company/user/unit/document/draft/chat row is
# gone. Correct by construction (no hand-maintained table list to keep in
# sync with new migrations), unlike TRUNCATE-ing tables by name.
reset-db:
	docker compose exec backend alembic downgrade base
	docker compose exec backend alembic upgrade head

# The LangGraph checkpointer's tables (checkpoints/checkpoint_blobs/
# checkpoint_writes/checkpoint_migrations) live in the same Postgres
# database but are deliberately excluded from Alembic (see alembic/env.py's
# _CHECKPOINT_TABLE_PREFIX) -- AsyncPostgresSaver.setup() owns them instead,
# so reset-db alone does not touch them. Dropping them here is safe: the
# backend recreates them itself the next time it boots (app.lifespan calls
# init_checkpointer() before it seeds anything).
reset-checkpoints:
	docker compose exec db psql -U $${POSTGRES_USER:-postgres} -d $${POSTGRES_DB:-kachow} \
		-c "DROP TABLE IF EXISTS checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations CASCADE;"

# Company profile/adapter/rules and rate-limit state are cached in Redis
# with a short TTL (see app.domains.companies.provider) -- harmless to drop,
# everything behind it re-reads from Postgres on the next request.
reset-cache:
	docker compose exec redis redis-cli FLUSHALL

# Uploaded documents and their *_analysis.json caches under
# backend/storage_data/uploads live on a host bind mount (compose.yml), so
# neither reset-db nor a Docker volume wipe touches them -- after a DB
# reset they no longer correspond to any row at all. Run inside the backend
# container so this works regardless of the host user's permissions on the
# bind-mounted files.
reset-storage:
	docker compose exec backend sh -c 'rm -rf storage_data/uploads/* storage_data/uploads/.[!.]*' 2>/dev/null || true

# The document_qa Qdrant collection holds per-document Q&A chunks (see
# app.domains.documents.service._index_for_qa) -- distinct from the
# mevzuat/örnek-yazışma collections this target never touches. Safe to
# drop: DocumentService recreates it automatically the next time any
# document is analyzed (create_collection is already idempotent there).
reset-document-qa:
	curl -sf -X DELETE http://localhost:6333/collections/document_qa || true

# The one-command "wipe everything app-level and hand me a fresh system"
# entry point -- irreversible, so it requires an explicit CONFIRM=yes
# rather than running on a bare `make reset`. Ends by restarting the
# backend so app.lifespan's own seeding chain (companies -> users -> units)
# repopulates a clean demo company/root/admin/manager/employee set.
reset:
	@if [ "$(CONFIRM)" != "yes" ]; then \
		echo "This permanently deletes ALL application data: companies, users,"; \
		echo "documents, drafts and chat history (mevzuat/örnek search indexes"; \
		echo "are left untouched). Re-run as: make reset CONFIRM=yes"; \
		exit 1; \
	fi
	$(MAKE) reset-db
	$(MAKE) reset-checkpoints
	$(MAKE) reset-cache
	$(MAKE) reset-storage
	$(MAKE) reset-document-qa
	docker compose restart backend
	@echo "Reset complete: backend restarted and reseeded a clean demo company + accounts."
