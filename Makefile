.PHONY: setup-db up down logs test eval eval-baseline

setup-db:
	docker compose exec db psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'langfuse'" | grep -q 1 || docker compose exec db psql -U postgres -c "CREATE DATABASE langfuse"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Redis is required, not optional: rate_limit() sits in front of the document
# endpoints, so without it seven API tests fail with a connection error that
# looks exactly like a product defect. --no-deps here cost several hours of
# misattributing those failures to a library version drift.
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
