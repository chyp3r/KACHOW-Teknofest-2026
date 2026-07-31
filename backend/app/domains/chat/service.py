"""Backwards-compatible re-export.

The chat service lives in :mod:`app.domains.chat.chat_service`. This module used
to hold an unrelated empty ``ChatService`` stub, which shadowed the real one for
anyone importing from the conventional location.
"""

from app.domains.chat.chat_service import ChatService

__all__ = ["ChatService"]
