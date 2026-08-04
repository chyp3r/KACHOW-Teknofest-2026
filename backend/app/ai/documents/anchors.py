"""Page-level addressing for extracted documents.

Extraction already produces per-page text (`ExtractedDocument.pages`), but
until now it was flattened into one string and thrown away. `PageMap` keeps
the mapping from a character offset in that flattened text back to the page
it came from, so a chunk's `start_index` (see
`app.ai.embeddings.chunking.recursive.RecursiveChunker`) can be labelled with
a real page number instead of being an anonymous span.
"""

import dataclasses

#: Matches how every extractor joins `ExtractedDocument.pages` into `.text`
#: (see `app/infrastructure/extractors/*.py`) and how
#: `app/domains/documents/service.py` re-joins the scrubbed pages.
PAGE_SEPARATOR = "\n\n"


@dataclasses.dataclass(frozen=True)
class PageMap:
    """Maps character offsets in the joined document text to page numbers."""

    #: Char offset each page starts at in the joined text; boundaries[i] is
    #: where the (i + 1)-th, 1-based, page begins.
    boundaries: tuple[int, ...]

    @property
    def page_count(self) -> int:
        return len(self.boundaries)

    def page_for_offset(self, offset: int) -> int:
        """The 1-based page a character offset in the joined text falls on.

        Args:
            offset: Character offset into the joined document text.

        Returns:
            The 1-based page number. Defaults to page 1 when there is no
            page information at all, and clamps to the last known page for
            an offset past the end of the mapped text.
        """
        if not self.boundaries:
            return 1
        page = 1
        for index, start in enumerate(self.boundaries):
            if offset < start:
                break
            page = index + 1
        return page


def build_page_map(pages: list[str], separator: str = PAGE_SEPARATOR) -> PageMap:
    """Build a `PageMap` from the same pages, joined the same way, as `.text`.

    Args:
        pages: Per-page extracted text, in document order.
        separator: The string the pages are joined with -- must match
            whatever produced the joined text or offsets drift.

    Returns:
        A `PageMap` covering every page.
    """
    boundaries: list[int] = []
    cursor = 0
    for page in pages:
        boundaries.append(cursor)
        cursor += len(page) + len(separator)
    return PageMap(boundaries=tuple(boundaries))


def format_anchor(page: int) -> str:
    """Render a page number as the citation shown to the model and user."""
    return f"[s. {page}]"
