import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PromptManager:
    """SOTA Prompt Manager that loads, caches, and renders prompt templates from disk.

    Decouples prompt text from application code and resolves braces conflicts with JSON samples.
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """Initialize Prompt Manager.

        Args:
            templates_dir: Optional path to the templates folder. If not provided,
                           defaults to the 'templates' folder relative to this file.
        """
        if templates_dir:
            self.templates_dir = templates_dir
        else:
            self.templates_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "templates"
            )

        self._cache: Dict[str, str] = {}
        logger.info(f"Initialized PromptManager with templates_dir: {self.templates_dir}")

    def get_template(self, name: str) -> str:
        """Read prompt template from disk or retrieve from cache.

        Args:
            name: Template name (e.g., 'orchestrator' or 'orchestrator.md').
        """
        # Normalize name: ensure it has .md extension
        base_name = name
        if not base_name.endswith(".md"):
            base_name += ".md"

        if base_name in self._cache:
            return self._cache[base_name]

        file_path = os.path.join(self.templates_dir, base_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"Prompt template '{base_name}' not found at path: {file_path}"
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._cache[base_name] = content
            logger.debug(f"Loaded and cached prompt template: {base_name}")
            return content
        except Exception as e:
            logger.error(
                f"Failed to read prompt template '{base_name}': {e}", exc_info=True
            )
            raise

    def render(self, name: str, **kwargs: Any) -> str:
        """Render prompt template replacing placeholders in the format {{variable}}.

        This avoids conflict with single curly braces {} used in JSON schema blocks.

        Args:
            name: Template name.
            **kwargs: Placeholder variables to replace.
        """
        template = self.get_template(name)
        rendered = template

        # Replace {{variable}} with value
        for key, value in kwargs.items():
            placeholder = f"{{{{{key}}}}}"
            rendered = rendered.replace(placeholder, str(value))

        return rendered

    def clear_cache(self) -> None:
        """Clear the template cache."""
        self._cache.clear()
        logger.debug("PromptManager cache cleared.")
