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

    #: /documents/* and /chat/* are unauthenticated by default so the
    #: competition demo works without the frontend implementing a login flow
    #: first. A full JWT + Redis-blacklist stack already exists for /auth and
    #: /users; flip this once the frontend sends an Authorization header, or
    #: for any deployment reachable outside a trusted demo network -- these
    #: routes hold a local model busy for tens of seconds per request and read
    #: whatever storage_path they're given.
    REQUIRE_AUTH: bool = False

    #: Persist each planning-graph run's decision trail to Postgres (see
    #: app.observability.run_recorder). On by default in every real
    #: deployment; tests flip it off globally (see conftest.py's
    #: `_disable_run_recording` autouse fixture) so the hundreds of unit
    #: tests that exercise the graph for unrelated reasons don't each also
    #: attempt a real database write.
    RUN_RECORDING_ENABLED: bool = True

    # Ollama Configuration
    # Note: When running inside Docker, set OLLAMA_BASE_URL to http://host.docker.internal:11434
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_TEMPERATURE: float = 0.7
    # Vision-language model used to OCR degraded scans (see extractors/vision.py).
    OLLAMA_VISION_MODEL: str = "glm-ocr:latest"
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


settings = Settings()
