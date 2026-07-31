from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "KACHOW-Teknofest-2026"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "supersecretkeychangeinproduction"

    # Database Configuration
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Ollama Configuration
    # Note: When running inside Docker, set OLLAMA_BASE_URL to http://host.docker.internal:11434
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_TEMPERATURE: float = 0.7
    # Vision-language model used to OCR degraded scans (see extractors/vision.py).
    OLLAMA_VISION_MODEL: str = "glm-ocr:latest"
    OLLAMA_REASONING: bool = False
    OLLAMA_MAX_TOKENS: int = 1024

    # vLLM Configuration
    VLLM_BASE_URL: str = "http://localhost:8000/v1"
    VLLM_MODEL: str = "qwen3.5:9b"

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

    # Legislation (Mevzuat) Corpus Configuration
    MEVZUAT_CORPUS_DIR: str = "./datasets/mevzuat"
    MEVZUAT_COLLECTION_NAME: str = "mevzuat"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
