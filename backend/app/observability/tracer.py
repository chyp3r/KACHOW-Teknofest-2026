import logging
from typing import Any, Optional
from langfuse.langchain import CallbackHandler
from app.core.config import settings

logger = logging.getLogger(__name__)

_callback_handler: Optional[CallbackHandler] = None

def get_langfuse_callback() -> Optional[CallbackHandler]:
    """Get or initialize the Langfuse Callback Handler for LangChain / LangGraph."""
    global _callback_handler
    
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning(
            "Langfuse tracking is disabled. "
            "Please configure LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to enable tracing."
        )
        return None
        
    if _callback_handler is None:
        try:
            import os
            if settings.LANGFUSE_PUBLIC_KEY:
                os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
            if settings.LANGFUSE_SECRET_KEY:
                os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
            if settings.LANGFUSE_HOST:
                os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST

            _callback_handler = CallbackHandler(
                public_key=settings.LANGFUSE_PUBLIC_KEY
            )
            logger.info("Langfuse callback handler initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Langfuse callback handler: {e}", exc_info=True)
            return None

    return _callback_handler


def build_trace_config(
    *,
    langfuse_user_id: Optional[str] = None,
    langfuse_session_id: Optional[str] = None,
    langfuse_tags: Optional[list[str]] = None,
    **configurable: Any,
) -> dict[str, Any]:
    """Build a LangGraph config: given configurable keys plus Langfuse tracing.

    Replaces three identical private ``_trace_config`` copies that used to
    live in ``ChatService``, ``DocumentService`` and ``DraftService``.

    The ``langfuse_*`` keyword-only params (as opposed to ``**configurable``,
    which only ever reaches LangGraph's own node functions) become
    ``config["metadata"]`` -- these specific key names are what the
    ``langfuse-langchain`` callback handler reads to attribute a trace to a
    user/session/tag set (see the Faz 6 tenancy-plan section on company-
    tagged observability). Company-scoping a trace this way is honest but
    unverified: ``compose.yml`` still runs ``langfuse/langfuse:2`` against
    the ``langfuse`` v4 Python SDK dependency, a version pair this repo's own
    prior notes already flag as likely incompatible (self-hosting v3+
    requires ClickHouse/MinIO this project does not run) -- tagging costs
    nothing extra to add and will simply start working the day tracing
    itself does, but ``runs``/``run_steps``/``guardrail_events`` remain the
    verified, always-on observability story today, not this.

    Args:
        langfuse_user_id: The caller's id, when known.
        langfuse_session_id: The chat thread/session id, when there is one.
        langfuse_tags: Free-form tags, e.g. ``[f"company:{slug}",
            f"role:{role}"]`` -- omit entirely (not just pass ``[]``) when
            neither is known, so an empty list never overwrites a real one
            the handler might otherwise infer.
        **configurable: Values merged into ``config["configurable"]`` (e.g.
            ``thread_id``, ``status_queue``). Omit for a plain, tracing-only
            config.

    Returns:
        A LangGraph-shaped config dict. Tracing degrades to absent rather than
        raising -- a document upload or a chat turn must not fail because
        Langfuse is unreachable.
    """
    config: dict[str, Any] = {}
    if configurable:
        config["configurable"] = dict(configurable)

    handler = get_langfuse_callback()
    if handler:
        config["callbacks"] = [handler]

    metadata: dict[str, Any] = {}
    if langfuse_user_id:
        metadata["langfuse_user_id"] = langfuse_user_id
    if langfuse_session_id:
        metadata["langfuse_session_id"] = langfuse_session_id
    if langfuse_tags:
        metadata["langfuse_tags"] = langfuse_tags
    if metadata:
        config["metadata"] = metadata

    return config


def company_tags(company_id: Optional[str], role: Optional[str] = None) -> Optional[list[str]]:
    """Build the ``langfuse_tags`` list for `build_trace_config`, `["company:<slug>",
    "role:<role>"]`, omitting whichever half is unknown -- `None` (not `[]`)
    when neither is, so callers can pass this straight through without an
    extra `if` at every one of the (several) call sites this is shared
    across.

    Reuses `app.observability.company_metrics`' already-populated slug cache
    (see that module) rather than querying the database again here --
    tracing must never be the reason a request pays an extra query.
    """
    from app.observability import company_metrics

    tags: list[str] = []
    if company_id:
        slug = company_metrics.cached_slug(company_id) or company_id
        tags.append(f"company:{slug}")
    if role:
        tags.append(f"role:{role}")
    return tags or None
