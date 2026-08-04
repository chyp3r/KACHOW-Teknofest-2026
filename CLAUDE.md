# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rule precedence

[AGENTS.md](AGENTS.md) is the project's authoritative rulebook and outranks this file. Its declared precedence order is: `AGENTS.md` → `README.md` → `docs/architecture/` → `docs/development/` → source code. Before non-trivial work, read the relevant docs in `docs/architecture/` (system design) and `docs/development/` (standards). All project docs are written in Turkish.

**Mandatory:** every meaningful change (code, template, schema, architecture) must be recorded in [CHANGELOG.md](CHANGELOG.md) under a version heading, in Turkish, using the existing `### Eklendi` / `### Değişti` sections.

## Repository state (important)

Most of the tree is scaffolding. **Large numbers of `.py` files exist but are empty placeholders** — check before assuming a module has content.

Implemented today:
- `backend/app/ai/**` — the bulk of the real code (agents, workflows, retrieval, embeddings, memory, prompts, LLM clients)
- `backend/app/api/{exceptions,middleware,responses}/`, `api/router.py`, `api/v1/health.py`
- `backend/app/core/` (config, enums, constants, permissions; `security.py` is a deliberate NotImplementedError skeleton)
- `backend/app/infrastructure/` (Redis cache, async SQLAlchemy session, Qdrant store, local/S3 storage, Ollama/vLLM providers)
- `backend/tests/unit/{ai,api,core,infrastructure}/`

Empty placeholders (do not assume they work): all of `backend/app/domains/**`, `app/mcp/**`, `app/events/**`, `app/workers/**`, `app/observability/**`, `app/api/dependencies.py`, every `api/v1/*.py` except `health.py`, `app/lifespan.py`, `backend/pyproject.toml`, the root `Makefile`, `alembic/env.py` (no `alembic.ini` — migrations are not wired), and **the entire `frontend/`** (`package.json`, `vite.config.ts`, `App.tsx` are all 0 bytes).

Two consequences worth knowing: `api/router.py` currently registers only the health router, and `core/security.py` reads `settings.SECRET_KEY`, which does not exist in `Settings` yet — whoever activates auth must add it to `app/core/config.py`.

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

Tests — run from `backend/` and invoke pytest **as a module**, so `backend/` lands on `sys.path` (there is no `conftest.py`, `pytest.ini`, or populated `pyproject.toml`, and the tests import `app.*`):

```bash
python -m pytest tests/unit -v
```

Single test:

```bash
python -m pytest tests/unit/ai/test_workflows.py::test_classification_graph -v
```

Inside the container (app code and tests are bind-mounted, `PYTHONPATH=/workspace`):

```bash
docker compose exec backend python -m pytest tests/unit -v
```

Live Ollama smoke test (needs Ollama running with `qwen3.5:9b` pulled):

```bash
python scripts/test_ai_core.py
```

`CONTRIBUTING.md` requires Ruff + Black before submitting, but neither is in `requirements.txt` and no lint config exists yet — nothing enforces formatting in-repo.

## Backend architecture

Strict one-way layering (`docs/development/backend-standards.md`): **Router → Service → Repository → Infrastructure → Database**. Routers are HTTP-only (no SQL, no AI calls, no business logic); services hold business logic but never build responses or write ORM queries; repositories only access data. Dependencies are injected, never constructed inline.

Features live in `app/domains/<domain>/` with a fixed five-file shape: `models.py` (SQLAlchemy), `schemas.py` (Pydantic request/response), `repository.py`, `service.py`, `router.py`. Add to an existing domain rather than creating a new one. Suggested ceilings: router ≤300 lines, service ≤500, repository ≤300.

The backend must not contain prompts, workflow orchestration, tool selection, or MCP calls — those belong to `app/ai/`. Conversely `app/ai/` must not contain HTTP endpoints, ORM usage, or direct DB access.

### API conventions

Every endpoint returns the unified envelope. Use `SuccessResponse(data=...)` / `ErrorResponse(...)` from `app.api.responses`, which wrap `APIResponse[T]` (`success`, `data`, `error`, `meta`). Raise subclasses of `BaseAppException` (`NotFoundException` 404, `ValidationException` 422, `AuthenticationException` 401, `AuthorizationException` 403, `ConflictException` 409, `AIException` 502) — the four global handlers registered in `app/main.py` convert them to the envelope and attach `request.state.response_time_ms` (set by `ResponseTimeMiddleware`) into `meta`. Do not add per-endpoint try/except that returns raw dicts.

RBAC uses `RoleChecker` from `app.core.permissions` as a FastAPI dependency; it reads `request.state.user_role`, which authentication middleware is expected to populate from the JWT.

All configuration flows through the `settings` singleton in `app/core/config.py` (pydantic-settings, `.env`). Never hardcode URLs, model names, ports, timeouts, or secrets.

## AI layer architecture (`backend/app/ai/`)

`docs/architecture/ai.md` is the detailed reference. Structure:

- **`llms/`** — `BaseLLMClient` ABC (`generate`, `stream`, `generate_structured`) with a `get_llm_client(provider=...)` factory; implementations live in `infrastructure/providers/` (Ollama, vLLM). Code depends on the ABC, never a concrete provider.
- **`agents/`** — `BaseAgent` plus 10 specialists (Orchestrator, NER, Classifier, Metadata, Writer, Editor, Verifier, Router, Reflection, Evaluator). Each specialist is a thin subclass whose only job is to load its system prompt via `PromptManager` and declare name/description. `BaseAgent.run_structured()` validates against a Pydantic model and, on failure, appends the validation error to the message list and retries — that self-correction loop is why agents return typed objects rather than parsed strings.
- **`prompts/`** — prompt text lives in `prompts/templates/*.md` (Turkish), never inline in Python. `PromptManager.render()` substitutes `{{variable}}` (double braces, deliberately, so JSON schema examples with single braces survive). Templates are cached in memory on first read.
- **`workflows/`** — five LangGraph subgraphs plus a master graph, each exposed as a `create_*_graph(...)` factory returning a compiled graph, with state as a `TypedDict`: `classification_graph` (Classify→NER→Metadata), `rag_graph` (Rewrite→Retrieve→Verify, looping back to rewrite with verifier feedback, max 2 attempts), `draft_graph` (Writer→Editor→Reflection→Evaluator), `routing_graph` (department vs. `HumanApproval` by confidence score), `system_graph` (background cache/cleanup/logging). `planning_graph` is the supervisor: `OrchestratorAgent` produces an ordered `PlanOutput` of step names and the executor node loops through them, invoking subgraphs and threading results forward (classification summary → RAG query → draft context → routing input). Every node catches its own exceptions and returns a safe fallback state rather than raising.
- **`retrieval/`** — `HybridRetriever` runs `DenseRetriever` (Qdrant) and `BM25Retriever` in parallel via `asyncio.gather`, over-fetches (`max(limit*2, 10)`), merges with `reciprocal_rank_fusion` (k=60), then truncates. `LLMReranker` is available as an extra stage.
- **`embeddings/`** — `EmbeddingService` composes a `BaseChunker` strategy (character, recursive, semantic, agentic) with a `BaseEmbeddingsClient` and returns `EmbeddedChunk` (text + vector + metadata), the unit `QdrantStore` consumes.
- **`memory/`** — `ConversationWindowMemory` (short-term), `SummaryMemory`, `VectorMemory` (semantic/episodic), all behind `BaseMemory`.

Everything is `async`. Adding a new agent means: template in `prompts/templates/`, subclass in `agents/`, export in `agents/__init__.py`. Adding a workflow means a new `*_graph.py` with a `create_*_graph` factory, exported from `workflows/__init__.py`, and a mocked unit test — tests patch `Agent.run_structured` and pass `MagicMock(spec=BaseLLMClient)`; never hit a live model in a test.

## Conventions

- **Language split:** all identifiers, docstrings, and code comments in English (Google-style `Args/Returns/Raises`). Prompt templates, Pydantic `Field(description=...)` text, and user-facing messages are Turkish. Docs and CHANGELOG entries are Turkish.
- **Naming:** `snake_case` files, plural `snake_case` folders, `PascalCase` classes, `UPPER_SNAKE_CASE` constants, plural resource-oriented endpoints (`/api/v1/documents`). Modules are single-noun files inside plural folders — the codebase deliberately replaced `enums.py`/`constants.py`/`permissions.py` with `core/enums/user_role.py`, `core/constants/system.py`, `core/permissions/role_checker.py`; follow that pattern instead of reintroducing plural module files.
- **Git:** never commit directly to `main`. Branch as `feature/`, `fix/`, `refactor/`, `docs/`, `test/`, `ci/`, or `hotfix/`; Conventional Commits with a scope (`feat(ai): ...`); one logical change per commit, one purpose per PR.
- **Before considering work done:** architecture respected, tests written and passing, docs and CHANGELOG updated (see the checklist at the end of `AGENTS.md`).
