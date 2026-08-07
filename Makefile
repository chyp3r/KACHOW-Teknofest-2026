.PHONY: setup-db bootstrap up down logs test eval eval-baseline eval-llm

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
