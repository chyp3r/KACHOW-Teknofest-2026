import shlex
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "KACHOW-Teknofest-2026"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "supersecretkeychangeinproduction"

    # Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

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

    #: On by default: /documents/* and /chat/* require a JWT bearer token,
    #: and the RBAC guardrail layer (app.core.permissions.role_checker,
    #: app.ai.guardrails.output_gate, document_tools.py's deny-at-retrieval
    #: check) only has a real requester to enforce clearance against when
    #: this is on. Set to False for local/offline demos with no frontend
    #: login flow -- REQUIRE_AUTH=False is a genuine "fully open" dev mode:
    #: ownership and clearance checks skip entirely rather than denying
    #: everything (see _verify_document_access / build_assistant_tools'
    #: own docstrings for the precise "None means skip" convention this
    #: relies on), so local testing isn't blocked, but nothing in that mode
    #: is protected -- never point it at a network reachable outside a
    #: trusted demo/dev environment.
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

    #: Create one ADMIN, one MANAGER and one EMPLOYEE account on startup if
    #: they don't already exist (see app.domains.users.seeder). Idempotent
    #: and best-effort like RUN_RECORDING_ENABLED; tests disable it globally
    #: (conftest.py's `_disable_default_user_seeding`) so a full-lifespan
    #: test doesn't also attempt real database writes. The passwords below
    #: are development/demo defaults -- override every SEED_* value for any
    #: deployment reachable outside a trusted demo environment.
    SEED_DEFAULT_USERS: bool = True
    SEED_ADMIN_EMAIL: str = "admin@kachow.local"
    SEED_ADMIN_PASSWORD: str = "Admin123!"
    SEED_MANAGER_EMAIL: str = "manager@kachow.local"
    SEED_MANAGER_PASSWORD: str = "Manager123!"
    SEED_EMPLOYEE_EMAIL: str = "employee@kachow.local"
    SEED_EMPLOYEE_PASSWORD: str = "Employee123!"

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

    # Langfuse Configuration
    LANGFUSE_PUBLIC_KEY: str | None = None
    LANGFUSE_SECRET_KEY: str | None = None
    LANGFUSE_HOST: str = "http://localhost:3000"

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
    def checkpointer_dsn(self) -> str:
        """``DATABASE_URL`` adapted for psycopg3, the checkpointer's driver.

        SQLAlchemy's asyncpg URL scheme (``postgresql+asyncpg://``) isn't a
        driver psycopg recognises; stripping the suffix lets both drivers
        share one connection string instead of keeping two in sync.
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def mevzuat_mcp_args(self) -> list[str]:
        """``MEVZUAT_MCP_ARGS`` split into an argv list for `subprocess`/MCP.

        `shlex.split`, not `str.split`: an arg containing a space (a quoted
        path with spaces, say) must survive as one argument rather than being
        cut in two.
        """
        return shlex.split(self.MEVZUAT_MCP_ARGS)


settings = Settings()
