import shlex
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "KACHOW-Teknofest-2026"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "supersecretkeychangeinproduction"

    # Database Configuration
    #: The app's own runtime connection. From Faz 3 (Postgres RLS) onward
    #: this is expected to be a restricted, non-owner role (``kachow_app`` --
    #: see migration ``0013_rls``): row-level security is only a real
    #: defense when the connection making the request cannot bypass it by
    #: virtue of owning the tables, which a superuser/owner connection
    #: always can regardless of any `ENABLE ROW LEVEL SECURITY` statement.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
    #: The schema-owner connection: Alembic migrations (DDL), and the
    #: narrow set of pre-tenant identity lookups (login, token refresh,
    #: invite-gated registration) that must search `users`/`invited_emails`
    #: by a globally-unique `username`/`email` *before* any company context
    #: exists to scope a row-level-security policy by -- see
    #: `app.infrastructure.database.session.get_owner_db`. Empty by default,
    #: which makes `effective_alembic_database_url` fall back to
    #: `DATABASE_URL` -- so a deployment that hasn't adopted the Faz 3 role
    #: split yet (both settings pointing at the same owner connection) keeps
    #: working exactly as before.
    ALEMBIC_DATABASE_URL: str = ""
    #: Password for the restricted `kachow_app` Postgres role migration
    #: `0013_rls` creates. Dev-only default, matching this repo's existing
    #: `POSTGRES_PASSWORD=postgres` convention (see `compose.yml`) -- never
    #: meant to be this value in a real deployment.
    KACHOW_APP_DB_PASSWORD: str = "kachow_app_dev_only"

    #: LangGraph's AsyncPostgresSaver, backing HITL (missing-info requests and
    #: draft approval) on the planning graph. Best-effort at startup: when
    #: False or when Postgres is unreachable, graphs compile without a
    #: checkpointer and everything except HITL keeps working.
    CHECKPOINTER_ENABLED: bool = True

    #: Gate the "draft needs a human's sign-off" interrupt separately from the
    #: "draft is missing information" one -- a demo can disable the approval
    #: gate without losing the information-request flow, which is the part
    #: the competition brief explicitly asks for.
    HITL_APPROVAL_GATE_ENABLED: bool = True

    #: Gate the pre-draft writing-brief interrupt (who's writing, who it's
    #: going to, closing formula -- see app.ai.workflows.writing_brief)
    #: separately from the post-draft approval gate above. Smart-skip means
    #: this only ever pauses a turn when a slot is genuinely unresolved, but
    #: a demo that wants zero pauses can still disable it outright.
    HITL_BRIEF_GATE_ENABLED: bool = True

    #: How many times the human approval gate's "revizyon iste" action may
    #: send the draft back through the revise sub-graph within the same run
    #: before the gate stops offering it (see planning_graph.gate_revise_node
    #: /route_after_gate). Bounds worst-case latency per turn -- without a
    #: cap, a human clicking "revizyon iste" repeatedly on a stubborn draft
    #: pays for an unbounded number of LLM calls in one request.
    HITL_MAX_GATE_REVISIONS: int = 2

    #: Whether a revision checks the user's own instruction against the
    #: retrieved mevzuat/source document for contradictions (see
    #: app.ai.revision.conflict). The deterministic layer always runs;
    #: this only gates the additional fast-tier LLM pass. Off does not mean
    #: "no warning" -- see the deterministic layer's own findings -- it means
    #: no second, reasoning-based opinion on top of them.
    REVISION_CONFLICT_AUDIT_ENABLED: bool = True

    #: Whether a revision whose instruction introduces new normative content
    #: (a law/article citation, an institution, a date) re-retrieves
    #: legislation before rewriting, instead of relying solely on the
    #: frozen context carried over from when the draft was first written.
    #: See app.ai.revision.retrieval.maybe_extend_context.
    REVISION_RERETRIEVAL_ENABLED: bool = True

    #: Hard ceiling on the conditional re-retrieval call so one slow Qdrant
    #: query cannot stall a revision -- degrades to the frozen context on
    #: timeout rather than blocking.
    REVISION_RERETRIEVAL_TIMEOUT_SECONDS: float = 10.0

    #: Ceiling on a single planning-graph run (chat, draft generation,
    #: routing). Env-configurable so a local run against a slow/CPU-only
    #: Ollama model can be given more headroom without a code change; the
    #: orchestrated chat flow multiplies this (see
    #: app.domains.chat.chat_service.ORCHESTRATION_TIMEOUT_SECONDS).
    AI_WORKFLOW_TIMEOUT_SECONDS: int = 480

    #: Mandatory as of the multi-tenancy work: every request to every
    #: router requires a JWT bearer token, and every row in the system now
    #: carries a `company_id` -- there is no longer an "unauthenticated
    #: demo/dev path" for a request to fall back to, since there would be
    #: no company to scope its reads/writes to. Kept as a settable flag
    #: only so `_require_auth_in_production` (app.lifespan) can still
    #: refuse to boot a misconfigured deployment; flipping it to False is
    #: not a supported mode and most routes will simply reject every
    #: request without one.
    REQUIRE_AUTH: bool = True

    #: Off by default. `rate_limit()` (app.api.rate_limit) keys its Redis
    #: counter on the caller's IP, read from the `X-Forwarded-For` header when
    #: this is on, or from `request.client.host` (the actual TCP peer, which a
    #: client cannot spoof) when it is off. Trusting X-Forwarded-For with no
    #: reverse proxy in front of the app lets every request carry its own
    #: fabricated IP, so each one lands in its own Redis key and the limiter
    #: never accumulates a count -- unlimited login attempts, unlimited
    #: uploads. Set to True only when the app sits behind a proxy that
    #: overwrites (not merely appends to) this header before it reaches here.
    TRUST_PROXY_HEADERS: bool = False

    #: Persist each planning-graph run's decision trail to Postgres (see
    #: app.observability.run_recorder). On by default in every real
    #: deployment; tests flip it off globally (see conftest.py's
    #: `_disable_run_recording` autouse fixture) so the hundreds of unit
    #: tests that exercise the graph for unrelated reasons don't each also
    #: attempt a real database write.
    RUN_RECORDING_ENABLED: bool = True

    #: Persist each chat turn (user message + assistant reply) to
    #: chat_sessions/chat_messages (see app.domains.chat.chat_recorder). Same
    #: best-effort, test-disabled convention as RUN_RECORDING_ENABLED.
    CHAT_HISTORY_ENABLED: bool = True

    #: Persist each generated/revised draft to the `drafts` version chain
    #: (see app.domains.drafts.draft_recorder). Same best-effort,
    #: test-disabled convention as RUN_RECORDING_ENABLED.
    DRAFT_HISTORY_ENABLED: bool = True

    #: Create one demo company on startup if it doesn't already exist (see
    #: app.domains.companies.seeder) -- the tenant every other seeded row
    #: below is anchored to, so this must run first. Same idempotent,
    #: best-effort, test-disabled convention as the other SEED_* flags.
    SEED_DEMO_COMPANY: bool = True
    SEED_DEMO_COMPANY_SLUG: str = "demo"
    SEED_DEMO_COMPANY_NAME: str = "Demo Kurum"

    #: Create one ROOT, one ADMIN, one MANAGER and one EMPLOYEE account on
    #: startup if they don't already exist (see app.domains.users.seeder).
    #: ROOT has no company (see UserModel.company_id); the other three are
    #: bound to the seeded demo company. Idempotent and best-effort like
    #: RUN_RECORDING_ENABLED; tests disable it globally (conftest.py's
    #: `_disable_default_user_seeding`) so a full-lifespan test doesn't
    #: also attempt real database writes. The passwords below are
    #: development/demo defaults -- override every SEED_* value for any
    #: deployment reachable outside a trusted demo environment.
    #:
    #: Domain is `.example` (RFC 2606, reserved for documentation), not
    #: `.local` -- `.local` is on `email_validator`'s SPECIAL_USE_DOMAIN_NAMES
    #: block-list (it's an mDNS reserved TLD, RFC 6762), so every
    #: `UserResponse` a seeded account round-trips through (e.g. `GET /users/
    #: me`) fails Pydantic's `EmailStr` validation with a 500 the instant a
    #: real HTTP request exercises it -- unit tests never caught this because
    #: they mock the service layer and never construct a real `UserResponse`
    #: from a seeded row.
    SEED_DEFAULT_USERS: bool = True
    SEED_ROOT_EMAIL: str = "root@kachow.example"
    SEED_ROOT_PASSWORD: str = "Root123!"
    SEED_ADMIN_EMAIL: str = "admin@kachow.example"
    SEED_ADMIN_PASSWORD: str = "Admin123!"
    SEED_MANAGER_EMAIL: str = "manager@kachow.example"
    SEED_MANAGER_PASSWORD: str = "Manager123!"
    SEED_EMPLOYEE_EMAIL: str = "employee@kachow.example"
    SEED_EMPLOYEE_PASSWORD: str = "Employee123!"

    #: Create the default routable units on startup, within the demo
    #: company, if it has none yet (see app.domains.units.seeder). Same
    #: idempotent, best-effort, test-disabled convention as
    #: SEED_DEFAULT_USERS -- without it a fresh environment has no units to
    #: route to until an admin creates one through `POST /units`.
    SEED_DEFAULT_UNITS: bool = True

    # Ollama Configuration
    # Note: When running inside Docker, set OLLAMA_BASE_URL to http://host.docker.internal:11434
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_TEMPERATURE: float = 0.7
    # Vision-language model used to OCR degraded scans (see extractors/vision.py
    # for the measurements behind this choice). Coupled to that module's
    # DEFAULT_PROMPT: deepseek-ocr returns nothing under the previous Turkish
    # prompt, so the two must move together.
    OLLAMA_VISION_MODEL: str = "deepseek-ocr"
    OLLAMA_REASONING: bool = False

    #: Generation budget. The previous value of 1024 truncated official drafts
    #: mid-sentence and cut off the editor's structured JSON, which then failed
    #: Pydantic validation and burned three retries before failing outright.
    OLLAMA_MAX_TOKENS: int = 4096

    #: Context window. Ollama defaults to 2048 and truncates *from the start* --
    #: silently dropping the system prompt or the document header, which is
    #: exactly where sayı/tarih/konu/muhatap live. Must be set globally, not
    #: per-node.
    OLLAMA_NUM_CTX: int = 8192

    #: How long Ollama keeps a model resident after a request. Without this the
    #: model is evicted between pipeline steps and every step pays the reload.
    OLLAMA_KEEP_ALIVE: str = "30m"

    #: Optional small model for cheap, low-token decisions (intent, routing,
    #: query classification). Falls back to OLLAMA_MODEL when unset, so an
    #: environment that has not pulled a second model keeps working.
    OLLAMA_FAST_MODEL: str | None = None

    #: Generation budget for the fast model. Intent and routing outputs are a
    #: label plus one sentence; anything larger is the model rambling.
    OLLAMA_FAST_MAX_TOKENS: int = 512

    #: Warm both models on startup so the first user request does not pay the
    #: cold-load cost (several seconds on Apple Silicon).
    OLLAMA_WARMUP_ON_STARTUP: bool = True

    #: Escape hatch for the hybrid draft quality gate's LLM judge leg (fast
    #: tier, ~5-7s per draft). Flip off on a thermally throttled demo machine
    #: without a code change; the deterministic verifier still runs either way.
    DRAFT_JUDGE_ENABLED: bool = True

    #: Hard ceiling on the judge call so one slow generation cannot blow the
    #: ~90s draft latency budget.
    DRAFT_JUDGE_TIMEOUT_SECONDS: float = 30.0

    #: Escape hatch for the guardrail nuance layer's LLM judge (fast tier) --
    #: same role as DRAFT_JUDGE_ENABLED, for the input sensitivity/output
    #: leakage judgements the deterministic pattern layer can't see. The
    #: deterministic guardrail checks (PII regex, gizlilik_derecesi mapping,
    #: groundedness) still run either way; this only degrades to
    #: deterministic-only, never removes a check.
    GUARDRAIL_JUDGE_ENABLED: bool = True

    #: Hard ceiling on the guardrail judge call. Fails open (deterministic-
    #: only) on timeout rather than blocking the request -- see
    #: app.ai.guardrails.llm_nuance's module docstring.
    GUARDRAIL_JUDGE_TIMEOUT_SECONDS: float = 15.0

    # Embedding Configuration
    EMBEDDING_PROVIDER: str = "ollama"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text:latest"

    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant Vector DB Configuration
    QDRANT_URL: str = "http://localhost:6333"

    # Storage Configuration
    STORAGE_TYPE: str = "local"  # "local" or "s3"
    LOCAL_STORAGE_DIR: str = "./storage_data"
    S3_BUCKET_NAME: str = "kachow-bucket"
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    #: SFT/DPO JSONL exports + LoRA adapter weights, one subdirectory per
    #: `{company_slug}/{run_id}` (Faz C3 Aşama 3, #191). Only ever written by
    #: the training worker (`app.workers.training`), never the main backend
    #: process -- kept as its own setting rather than reusing
    #: LOCAL_STORAGE_DIR since these are large, disposable training
    #: artifacts, not user-facing document storage.
    TRAINING_ARTIFACTS_DIR: str = "./artifacts/training"

    # Langfuse Configuration
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    #: The backend's own API endpoint -- in `compose.yml` this is the
    #: internal Docker service hostname (`http://langfuse:3000`), reachable
    #: from this container but *not* from a browser. Do not reuse this for
    #: a link a human is meant to click; see `LANGFUSE_PUBLIC_URL` below.
    LANGFUSE_HOST: str = "http://localhost:3000"

    #: The browser-reachable URL for the same Langfuse instance -- used only
    #: by `GET /companies/{id}/analytics/links`'s deep link. Defaults to the
    #: same value as `LANGFUSE_HOST` for a non-Docker/local run where the two
    #: really are identical; `compose.yml` overrides only `LANGFUSE_HOST`
    #: (to the internal hostname), so this keeps its `localhost` default
    #: there and the two intentionally diverge under Docker.
    LANGFUSE_PUBLIC_URL: str = "http://localhost:3000"

    #: Base URL for `GET /companies/{id}/analytics/links`'s deep link --
    #: `compose.yml`'s `grafana` service publishes on 3001 (Prometheus/
    #: Postgres already use 3000/5432, hence not the Grafana default port).
    #: The `company` dashboard template variable (see `monitoring/
    #: dashboards/company_dashboard.json`) is appended by the analytics
    #: service, not baked in here, since it varies per company.
    GRAFANA_URL: str = "http://localhost:3001"

    # Semantic prototype vectors, written by scripts/build_prototypes.py.
    # Same relative-to-working-directory convention as the corpus below, which
    # is what makes it resolve identically in the container (/workspace) and in
    # a host run from the repo root.
    PROTOTYPE_DIR: str = "./datasets/prototypes"

    # Legislation (Mevzuat) Corpus Configuration
    MEVZUAT_CORPUS_DIR: str = "./datasets/mevzuat"
    MEVZUAT_COLLECTION_NAME: str = "mevzuat"

    # Draft few-shot style examples, curated by
    # scripts/curate_yazisma_examples.py from datasets/resmi_yazisma. Indexed
    # unchunked (one official letter = one point) -- see
    # scripts/index_yazisma_examples.py.
    RESMI_YAZISMA_EXAMPLES_PATH: str = "./datasets/resmi_yazisma/ornekler.jsonl"
    RESMI_YAZISMA_COLLECTION_NAME: str = "resmi_yazisma_ornek"

    # Live legislation lookup over MCP (github.com/saidsurucu/mevzuat-mcp, MIT),
    # querying mevzuat.gov.tr directly.
    #
    # Two independent switches read this same server:
    #
    # * MEVZUAT_SOURCE decides where document analysis's legislation retrieval
    #   (app.ai.retrieval.mcp_mevzuat) reads from. "mcp" (default) fetches the
    #   curated corpus's current official text live and falls back to the
    #   committed corpus under MEVZUAT_CORPUS_DIR on any failure; "local" skips
    #   MCP entirely and always uses the committed corpus, exactly as before
    #   this setting existed. Neither value ever touches compliance:
    #   check_required_fields is set subtraction over a rule table with
    #   hard-coded article numbers, and no source switch reaches that code.
    # * MEVZUAT_MCP_ENABLED (default off) is the assistant's own switch,
    #   offering search_legislation_live as an escalation when the local
    #   corpus tool finds nothing. Independent of MEVZUAT_SOURCE on purpose --
    #   a deployment can run document analysis against live legislation
    #   without also handing the chat model a live government-site tool, or
    #   the reverse.
    #
    # register_servers() registers the server whenever *either* switch wants
    # it, so the documented default (MEVZUAT_SOURCE="mcp",
    # MEVZUAT_MCP_ENABLED=False) still actually reaches the server instead of
    # silently registering nothing.
    #
    # The server is not in the backend image -- its dependency tree pins
    # playwright and pulls a browser binary -- so either switch needs the
    # command below to point at an installed copy (an isolated venv locally,
    # or a sidecar container). Command and args live here rather than in code
    # so that swap is configuration.
    MEVZUAT_SOURCE: Literal["mcp", "local"] = "mcp"
    MEVZUAT_MCP_ENABLED: bool = False
    MEVZUAT_MCP_COMMAND: str = "mevzuat-mcp"
    #: Space-separated, not a list. pydantic-settings JSON-decodes any env var
    #: bound to a structured type (list, dict, ...) *before* the model's own
    #: validators ever run, so a plain `list[str]` field made
    #: `MEVZUAT_MCP_ARGS="--transport stdio"` -- the obvious shell-style value
    #: -- a hard crash at `Settings()` construction: "error parsing value for
    #: field ... from source EnvSettingsSource", with no mention of JSON and no
    #: chance to fix it in a validator. A plain `str` field is read as a raw
    #: string, so this type is what actually avoids the crash; use
    #: `mevzuat_mcp_args` below to get the parsed list.
    MEVZUAT_MCP_ARGS: str = ""
    #: Cap on one lookup. The government site publishes no rate limit and the
    #: assistant must not stall a chat turn waiting on it.
    MEVZUAT_MCP_TIMEOUT_SECONDS: float = 25.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    @property
    def effective_alembic_database_url(self) -> str:
        """``ALEMBIC_DATABASE_URL``, or ``DATABASE_URL`` when unset.

        The one place that resolves the fallback -- every other reader
        (``alembic/env.py``, ``checkpointer_dsn`` below, ``app.infrastructure.
        database.session.get_owner_db``) uses this property, never the raw
        setting, so the fallback logic exists in exactly one place.
        """
        return self.ALEMBIC_DATABASE_URL or self.DATABASE_URL

    @property
    def checkpointer_dsn(self) -> str:
        """The schema-owner connection, adapted for psycopg3, the checkpointer's driver.

        Deliberately ``effective_alembic_database_url``, not ``DATABASE_URL``:
        ``AsyncPostgresSaver.setup()`` runs ``CREATE TABLE IF NOT EXISTS`` for
        its own checkpoint tables on every boot, which a restricted,
        non-owner ``DATABASE_URL`` role (see that setting's own docstring)
        has no privilege to do. The checkpoint tables are already excluded
        from Alembic/RLS entirely (see ``alembic/env.py``'s
        ``_CHECKPOINT_TABLE_PREFIX`` exclusion) -- they were always meant to
        be self-managed outside the tenancy model, so owning their own
        connection independent of the app's row-level-security posture is
        consistent, not a workaround.

        SQLAlchemy's asyncpg URL scheme (``postgresql+asyncpg://``) isn't a
        driver psycopg recognises; stripping the suffix lets both drivers
        share one connection string instead of keeping two in sync.
        """
        return self.effective_alembic_database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def mevzuat_mcp_args(self) -> list[str]:
        """``MEVZUAT_MCP_ARGS`` split into an argv list for `subprocess`/MCP.

        `shlex.split`, not `str.split`: an arg containing a space (a quoted
        path with spaces, say) must survive as one argument rather than being
        cut in two.
        """
        return shlex.split(self.MEVZUAT_MCP_ARGS)


settings = Settings()
