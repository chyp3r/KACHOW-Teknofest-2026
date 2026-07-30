import logging
from typing import Optional
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
