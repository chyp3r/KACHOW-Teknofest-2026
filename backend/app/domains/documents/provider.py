"""Read-side access to a document's analysis cache for the planning graph.

Kept inside `app.domains.documents` rather than read from `app.ai` directly:
`app.ai.workflows.planning_graph` never imports `app.domains` (see
`docs/architecture/backend.md`, and `backend/tests/unit/ai/
test_ai_never_imports_domains.py`'s static enforcement of it), so this is
handed to the graph as a plain callable at construction time instead, the
same way `units_provider`/`adapter_provider` already are.
"""

import json
import logging

from app.domains.documents.cache_keys import analysis_cache_key
from app.infrastructure.storage import get_storage_client

logger = logging.getLogger(__name__)


async def get_cached_document(document_id: str) -> dict:
    """Read a previously analyzed document's cache for the planning graph.

    Reads through `get_storage_client()` -- the same backend a document's
    own bytes and its analysis cache live in (see `app.domains.documents.
    service._save_document_analysis_cache`) -- not a raw local-filesystem
    path. Degrades to an empty dict on any failure (missing key, unreadable
    JSON, a storage backend outage): a missing cache is a normal, frequent
    case (the user is referencing a document by name, not by a prior
    upload), not an error worth failing the whole planning step over.

    Args:
        document_id: The document's storage path.

    Returns:
        The cache payload (`extracted_text`/`pages`/`analysis` keys -- see
        `_save_document_analysis_cache`), or `{}` if there is nothing to
        load or reading/parsing it fails for any reason.
    """
    try:
        content = await get_storage_client().get_file(analysis_cache_key(document_id))
    except FileNotFoundError:
        return {}
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}

    try:
        return json.loads(content)
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}
