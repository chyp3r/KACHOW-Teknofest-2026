from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "KACHOW-Teknofest-2026"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    # Database Configuration (to be used later)
    DATABASE_URL: Optional[str] = None

    # Ollama Configuration
    # Note: When running inside Docker, set OLLAMA_BASE_URL to http://host.docker.internal:11434
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_TEMPERATURE: float = 0.7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
