.PHONY: setup-db up down logs

setup-db:
	docker compose exec db psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'langfuse'" | grep -q 1 || docker compose exec db psql -U postgres -c "CREATE DATABASE langfuse"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f
