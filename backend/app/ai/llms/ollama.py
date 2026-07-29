# Re-export OllamaClient from app.infrastructure.providers for backward compatibility
from app.infrastructure.providers.ollama import OllamaClient

__all__ = ["OllamaClient"]
