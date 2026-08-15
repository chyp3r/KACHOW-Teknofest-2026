"""Deterministic backstop for a generated draft's own "not found" markers.

The brief instructs the writer to leave a ``[...]`` placeholder for anything
missing (see ``app.ai.workflows.draft_graph._build_brief``), but a prompt
instruction is not a guarantee -- a smaller local model can still write a
header field's own line with a literal "bulunamadı"/"belirtilmemiş"/"yok"
value instead of the placeholder it was told to use. Left as plain text,
this silently bypasses the whole missing-information gate:
``PLACEHOLDER_PATTERN`` never matches it, so ``build_missing_info_request``
never asks the human for that field's value, and the draft ships as if the
field were genuinely, if concisely, filled in -- which is exactly the "no
question is ever asked" bug this module exists to close.
"""

import re
from typing import NamedTuple

from app.ai.verification.draft_verifier import _fold

#: Header line labels this backstop recognises, mapped to the bracket name
#: the field becomes when its value turns out to be an unfilled marker.
#: Matches the placeholder names ``writer.md`` itself already uses for these
#: fields (``[Belge Sayısı]``, ``[Tarih]``, ``[Konu]``, ``[Muhatap]``), so a
#: substitution here and one the writer left on its own are indistinguishable
#: to everything downstream (``build_missing_info_request``, the human gate).
_FIELD_PLACEHOLDERS: dict[str, str] = {
    "sayı": "Belge Sayısı",
    "sayi": "Belge Sayısı",
    "tarih": "Tarih",
    "konu": "Konu",
    "muhatap": "Muhatap",
}

#: Folded (ASCII, lowercase) values that mean "this field was not actually
#: filled in" -- a model writing one of these as a header line's value
#: instead of a `[...]` placeholder leaves the same information gap, just
#: not one `PLACEHOLDER_PATTERN` can see as written. The empty string is
#: included deliberately: folding strips all punctuation, so a value of
#: "---", "___" or "N/A" (which folds to "n a") already collapses to it or
#: to an explicit entry below -- and a value that is bare whitespace after
#: stripping is the same "nothing here" gap by construction.
_UNFILLED_MARKERS = frozenset(
    {
        "", "bulunamadi", "bulunamamistir", "belirtilmemis", "belirtilmemistir",
        "bilinmiyor", "mevcut degil", "yok", "n a", "na", "belirtilmedi",
        "bos",
    }
)

#: A recognised field label at the start of a line, colon, then its value.
#: Anchored to line start the same way ``STRUCTURE_CHECKS``'s own field
#: patterns are, so this only ever matches the draft's own header line for
#: that field -- never, say, an "İlgi:" line quoting another document's
#: number, which has its own label.
_HEADER_LINE_PATTERN = re.compile(
    r"^([ \t]*)(Sayı|Sayi|Tarih|Konu|Muhatap)([ \t]*:[ \t]*)(.+)$",
    re.MULTILINE | re.IGNORECASE,
)


class NormalizedDraft(NamedTuple):
    text: str
    substitutions: int


def normalize_unfilled_markers(draft: str) -> NormalizedDraft:
    """Rewrite a recognised header line's "not found" value into a placeholder.

    Args:
        draft: The generated draft text.

    Returns:
        The (possibly rewritten) draft, and how many lines were substituted
        -- callers that only care about the text can ignore the count, but
        it lets a caller log/observe how often the model actually needed
        this backstop.
    """
    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        indent, label, separator, value = match.groups()
        if _fold(value) not in _UNFILLED_MARKERS:
            return match.group(0)
        placeholder = _FIELD_PLACEHOLDERS.get(label.lower(), label)
        count += 1
        return f"{indent}{label}{separator}[{placeholder}]"

    normalized = _HEADER_LINE_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=normalized, substitutions=count)
