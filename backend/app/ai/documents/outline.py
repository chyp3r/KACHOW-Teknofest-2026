"""A cheap, LLM-free page listing.

Answering "3. sayfayı açıkla" needs the model to know a page 3 exists and
roughly what's on it before it can decide to read it -- this builds that
listing directly from extracted text (no generation call), so getting the
document's rough shape costs nothing.
"""

import dataclasses

#: Longest a page's preview line is allowed to be before it's cut.
PREVIEW_CHAR_LIMIT = 80


@dataclasses.dataclass(frozen=True)
class PageSummary:
    """One outline entry: a page number and its first non-blank line."""

    page: int
    preview: str


def build_outline(
    pages: list[str], preview_chars: int = PREVIEW_CHAR_LIMIT
) -> list[PageSummary]:
    """Build a one-line-per-page outline from a document's page texts.

    Args:
        pages: Per-page extracted text, in document order.
        preview_chars: Max length of each page's preview line.

    Returns:
        One `PageSummary` per page, in order.
    """
    summaries: list[PageSummary] = []
    for index, page_text in enumerate(pages, start=1):
        first_line = next(
            (line.strip() for line in page_text.splitlines() if line.strip()), ""
        )
        summaries.append(PageSummary(page=index, preview=first_line[:preview_chars]))
    return summaries


def format_outline(outline: list[PageSummary]) -> str:
    """Render an outline as text a model or user can read directly.

    Args:
        outline: The outline built by `build_outline`.

    Returns:
        One line per page, or a fallback message when there are no pages.
    """
    if not outline:
        return "Bu belge için sayfa bilgisi bulunmuyor."
    return "\n".join(
        f"s.{summary.page}: {summary.preview or '(boş sayfa)'}" for summary in outline
    )
