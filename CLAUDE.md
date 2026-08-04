# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rule precedence

[AGENTS.md](AGENTS.md) is the project's authoritative rulebook and outranks this file. Its declared precedence order is: `AGENTS.md` → `README.md` → `docs/architecture/` → `docs/development/` → source code. Before non-trivial work, read the relevant docs in `docs/architecture/` (system design) and `docs/development/` (standards). All project docs are written in Turkish.

**Mandatory:** every meaningful change (code, template, schema, architecture) must be recorded in [CHANGELOG.md](CHANGELOG.md) under a version heading, in Turkish, using the existing `### Eklendi` / `### Değişti` sections.

## Repository state

The tree is substantially built out. Backend, frontend, auth, migrations, observability and both competition tasks have real implementations; the remaining empty files are a handful of `__init__.py` plus `app/mcp/registry.py` and `app/domains/routing/`.

Landmarks worth knowing before changing anything:

- **`backend/app/ai/**`** is the bulk of the code — agents, LangGraph workflows, retrieval, embeddings, prompts, guardrails, the decision policy layer, and the evaluation harness.
- **Auth is live.** `get_current_user` / `require_roles` in `app/api/dependency.py`, JWT in `core/security.py`, `SECRET_KEY` present in `Settings`. `require_auth_if_enabled` gates the document router.
- **Schema exists only through Alembic.** Nothing calls `create_all`. `0001_baseline` covers `users` / `invited_emails`; `0002_documents_analysis_table` adds `documents`. LangGraph's checkpoint tables are *not* in Alembic — `AsyncPostgresSaver.setup()` creates them at startup and `env.py` excludes them from autogenerate.
- **`app/lifespan.py` warms models and graphs at boot** and opens the Postgres checkpointer. Every step is best-effort so the API boots with Ollama or Postgres down.
- The document analysis graph runs **classification and field extraction as a single merged model call** (`_build_merged_output_model`), with a two-tier degradation ladder behind it. Do not re-split them.

Two traps that cost real time:

- Local `pytest` leaves **7 API tests failing** — they need Redis. `make test` (`docker compose run --rm backend pytest -q`) is the real gate. `tests/unit/evaluation/` additionally needs the repo root on `PYTHONPATH`, so it only collects inside the container.
- Documents persist to PostgreSQL **and** to local JSON files, with the JSON path as the fallback when the database is unreachable. Changing one without the other makes the library view disagree with itself.

## Commands

Docker is the intended dev path. Use the **root** `compose.yml` (its build context is `./`); `deploy/docker/docker-compose.dev.yml` is a near-duplicate that differs in the Postgres image (`pgvector/pgvector:pg16` vs `postgres:15`).

```bash
docker compose up --build
```

Backend without Docker (from `backend/`):

```bash
pip install -r requirements.txt && uvicorn app.main:app --reload
```

The local env is the `kachow` conda env (Python 3.12). Under a non-interactive shell
the `conda` shell function fails with `__conda_exe: permission denied` because
`CONDA_EXE` is unset — call the binary directly instead:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/kachow/bin/python -m pytest tests/unit -q
```

**Database schema exists only through Alembic** — nothing calls `create_all` and
there is no startup hook that creates tables. Run this before the first request that
persists anything:

```bash
make migrate
```

Tests — **the real gate runs in Docker**, because seven API tests need Redis and `tests/unit/evaluation/` needs the repo root on `PYTHONPATH`:

```bash
make test
```

Locally (from `backend/`; `pyproject.toml` sets `pythonpath = ["."]` and `asyncio_mode = "auto"`, and `tests/conftest.py` provides `FakeLLMClient` — prefer it over hand-rolled mocks). Expect the 7 Redis-dependent failures:

```bash
python -m pytest tests/unit --ignore=tests/unit/evaluation -q
```

Single test:

```bash
python -m pytest tests/unit/ai/test_workflows.py -q
```

Live Ollama smoke test (needs Ollama running with `qwen3.5:9b` pulled):

```bash
python scripts/test_ai_core.py
```

`CONTRIBUTING.md` requires Ruff + Black before submitting, but neither is in `requirements.txt` and no lint config exists yet — nothing enforces formatting in-repo.

## Backend architecture

Strict one-way layering (`docs/development/backend-standards.md`): **Router → Service → Repository → Infrastructure → Database**. Routers are HTTP-only (no SQL, no AI calls, no business logic); services hold business logic but never build responses or write ORM queries; repositories only access data. Dependencies are injected, never constructed inline.

Features live in `app/domains/<domain>/` as `service.py`, `repository.py`, `router.py` plus `model/<name>_model.py` and `schema/<name>_schema.py` **directories** (singular-noun modules inside singular folders, matching the `core/enums/user_role.py` pattern — not the plural `models.py` / `schemas.py` the older docs describe). Add to an existing domain rather than creating a new one. Suggested ceilings: router ≤300 lines, service ≤500, repository ≤300.

The backend must not contain prompts, workflow orchestration, tool selection, or MCP calls — those belong to `app/ai/`. Conversely `app/ai/` must not contain HTTP endpoints, ORM usage, or direct DB access.

### API conventions

Every endpoint returns the unified envelope. Use `SuccessResponse(data=...)` / `ErrorResponse(...)` from `app.api.responses`, which wrap `APIResponse[T]` (`success`, `data`, `error`, `meta`). Raise subclasses of `BaseAppException` (`NotFoundException` 404, `ValidationException` 422, `AuthenticationException` 401, `AuthorizationException` 403, `ConflictException` 409, `AIException` 502) — the four global handlers registered in `app/main.py` convert them to the envelope and attach `request.state.response_time_ms` (set by `ResponseTimeMiddleware`) into `meta`. Do not add per-endpoint try/except that returns raw dicts.

RBAC uses `RoleChecker` from `app.core.permissions` as a FastAPI dependency; it reads `request.state.user_role`, which authentication middleware is expected to populate from the JWT.

All configuration flows through the `settings` singleton in `app/core/config.py` (pydantic-settings, `.env`). Never hardcode URLs, model names, ports, timeouts, or secrets.

## AI layer architecture (`backend/app/ai/`)

`docs/architecture/ai.md` is the detailed reference. Structure:

- **`llms/`** — `BaseLLMClient` ABC (`generate`, `stream`, `generate_structured`) with a `get_llm_client(provider=...)` factory; implementations live in `infrastructure/providers/` (Ollama, vLLM). Code depends on the ABC, never a concrete provider.
- **`agents/`** — `BaseAgent`, a `TemplateAgent` base that removes the boilerplate subclass, and the specialists that remain after the dedupe: `assistant`, `classifier`, `compliance`, `judge`, `memory_summarizer`, `reviser`, `router`, `writer`. Each loads its system prompt via `PromptManager` and declares name/description. `BaseAgent.run_structured()` validates against a Pydantic model and, on failure, appends the validation error to the message list and retries — that self-correction loop is why agents return typed objects rather than parsed strings.
- **`prompts/`** — prompt text lives in `prompts/templates/*.md` (Turkish), never inline in Python. `PromptManager.render()` substitutes `{{variable}}` (double braces, deliberately, so JSON schema examples with single braces survive). Templates are cached in memory on first read.
- **`workflows/`** — LangGraph subgraphs exposed as `create_*_graph(...)` factories returning compiled graphs, with state as a `TypedDict`: `document_analysis_graph` (merged classify+extract → compliance → retrieve → suggest), `rag_graph`, `draft_graph`, `routing_graph`. `planning_graph` is the supervisor, driven by a readiness engine over a step DAG (`step_graph.py`) and a dispatch table rather than an index or an if/elif chain; `planner.py` resolves intent to a plan (`draft` / `analyze` / `assist`) using the rule and prototype layers in `app/ai/policy/`. Every node catches its own exceptions and returns a safe fallback state rather than raising; `resilience.py` supplies the retry and timeout decorators.
- **`retrieval/`** — `HybridRetriever` runs `DenseRetriever` (Qdrant) and `BM25Retriever` in parallel via `asyncio.gather`, over-fetches (`max(limit*2, 10)`), merges with `reciprocal_rank_fusion` (k=60), then truncates. `LLMReranker` is available as an extra stage.
- **`embeddings/`** — `EmbeddingService` composes a `BaseChunker` strategy (character, recursive, semantic, agentic) with a `BaseEmbeddingsClient` and returns `EmbeddedChunk` (text + vector + metadata), the unit `QdrantStore` consumes.
- **`tools/`** — `ToolSpec` / `build_assistant_tools`. The assistant's document tools are bound by closure to one `document_id` per request, so cross-document access is structurally impossible rather than merely disallowed; when there is no document they are not bound at all.
- **`policy/`** — the decision layer's parameters as one typed policy, plus semantic prototypes. `POLICY_VERSION` gates cached vectors: bump it and stale prototype files are ignored, which means `scripts/build_prototypes.py` must be re-run.
- **`compliance/`** — the deterministic core of Görev 1. `parse_labelled_fields` reads the regulation-prescribed header with regexes and `merge_parsed_over_model` makes the parser authoritative **in both directions** for `AUTHORITATIVE_FIELD`: where it found nothing, the model's value is discarded, because a model that fills a prescribed-but-absent field hides the very omission the pipeline exists to report.

Everything is `async`. Adding a new agent means: template in `prompts/templates/`, subclass in `agents/`, export in `agents/__init__.py`. Adding a workflow means a new `*_graph.py` with a `create_*_graph` factory, exported from `workflows/__init__.py`, and a mocked unit test — prefer `FakeLLMClient` from `tests/conftest.py`; never hit a live model in a test.

## Conventions

- **Language split:** all identifiers, docstrings, and code comments in English (Google-style `Args/Returns/Raises`). Prompt templates, Pydantic `Field(description=...)` text, and user-facing messages are Turkish. Docs and CHANGELOG entries are Turkish.
- **Naming:** `snake_case` files, plural `snake_case` folders, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, plural resource-oriented endpoints (`/api/v1/documents`). Modules are single-noun files inside plural folders — the codebase deliberately replaced `enums.py`/`constants.py`/`permissions.py` with `core/enums/user_role.py`, `core/constants/system.py`, `core/permissions/role_checker.py`; follow that pattern instead of reintroducing plural module files.
- **Git:** never commit directly to `main`. Branch as `feature/`, `fix/`, `refactor/`, `docs/`, `test/`, `ci/`, or `hotfix/`; Conventional Commits with a scope (`feat(ai): ...`); one logical change per commit, one purpose per PR.
- **Before considering work done:** architecture respected, tests written and passing, docs and CHANGELOG updated (see the checklist at the end of `AGENTS.md`).
