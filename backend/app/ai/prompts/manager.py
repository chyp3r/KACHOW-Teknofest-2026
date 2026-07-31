import logging
import os
import re
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

#: Placeholders are ``{{name}}``, never ``{name}``. The templates embed literal
#: JSON examples with single braces, so :meth:`str.format` cannot be used on
#: them -- it raises ``KeyError`` on the JSON keys. Every renderer in the
#: codebase must go through this module so the two conventions cannot drift
#: apart again.
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_placeholders(template: str, context: Mapping[str, Any]) -> str:
    """Substitute ``{{name}}`` placeholders in a template.

    Args:
        template: Raw template text.
        context: Values to substitute, keyed by placeholder name.

    Returns:
        The rendered text. Placeholders with no matching key are left verbatim,
        which keeps a partially supplied context readable instead of blanking
        the instruction.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            logger.warning("Prompt placeholder '{{%s}}' has no value; left as-is.", key)
            return match.group(0)
        return str(context[key])

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


class PromptManager:
    """Loads, caches and renders prompt templates from disk.

    Decouples prompt text from application code and keeps JSON examples inside
    templates safe from brace-based formatting.
    """

    def __init__(self, templates_dir: Optional[str] = None):
        """Initialize Prompt Manager.

        Args:
            templates_dir: Optional path to the templates folder. Defaults to the
                ``templates`` folder next to this file.
        """
        self.templates_dir = templates_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates"
        )
        self._cache: Dict[str, str] = {}
        logger.info("Initialized PromptManager with templates_dir: %s", self.templates_dir)

    def get_template(self, name: str) -> str:
        """Read a prompt template from disk, or return the cached copy.

        Args:
            name: Template name, with or without the ``.md`` extension.

        Returns:
            The template text.

        Raises:
            FileNotFoundError: If no such template exists.
        """
        base_name = name if name.endswith(".md") else f"{name}.md"

        cached = self._cache.get(base_name)
        if cached is not None:
            return cached

        file_path = os.path.join(self.templates_dir, base_name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(
                f"Prompt template '{base_name}' not found at path: {file_path}"
            )

        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception:
            logger.exception("Failed to read prompt template '%s'", base_name)
            raise

        self._cache[base_name] = content
        logger.debug("Loaded and cached prompt template: %s", base_name)
        return content

    def render(self, name: str, **kwargs: Any) -> str:
        """Load a template and substitute its ``{{variable}}`` placeholders.

        Args:
            name: Template name.
            **kwargs: Placeholder values.

        Returns:
            The rendered prompt.
        """
        return render_placeholders(self.get_template(name), kwargs)

    def clear_cache(self) -> None:
        """Clear the template cache."""
        self._cache.clear()
        logger.debug("PromptManager cache cleared.")


#: Templates are read-only at runtime, so one manager per process is enough and
#: saves every agent constructor a directory stat.
_default_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """Return the process-wide PromptManager."""
    global _default_manager
    if _default_manager is None:
        _default_manager = PromptManager()
    return _default_manager
