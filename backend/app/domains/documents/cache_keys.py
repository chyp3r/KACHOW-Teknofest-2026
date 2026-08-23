"""The analysis-cache key convention, standalone.

Split out from ``app.domains.documents.service`` so ``app.ai.workflows.
planning_graph`` (which needs the same key to read a document's cached
analysis via ``BaseStorage`` -- see ``_load_cached_document``) can share it
without importing the domain service module: the AI workflow layer reaching
into a domain service would invert this codebase's usual dependency
direction (domains import from ``app.ai.*``, not the reverse).
"""


def analysis_cache_key(storage_path: str) -> str:
    """The BaseStorage key an analysis-cache JSON is filed under.

    Same `self.storage`/backend the document's own bytes live in -- not
    necessarily local disk. See ``app.domains.documents.service.
    _save_document_analysis_cache`` for why that matters: routing this
    through the configured storage backend, not a raw local-filesystem
    path, is what makes the cache work under ``STORAGE_TYPE=s3`` and safe
    for more than one backend replica.
    """
    return f"{storage_path}_analysis.json"
