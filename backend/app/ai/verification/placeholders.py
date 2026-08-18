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

from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, _fold

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


#: The draft's own "Tarih:" header line, with a bracketed placeholder as its
#: value -- e.g. "Tarih: [Tarih]" or "Tarih: [Tarih Eksik - Lütfen
#: Doldurun]" (see writer.md and draft_graph.writer_node's own rule).
#: Anchored to a line starting with the "Tarih" label specifically, not any
#: `[...]` span mentioning a date anywhere in the draft -- the incoming
#: document's own date, when referenced at all, sits in the "İlgi:" line,
#: never behind this label, so this can never mistake it for the response's
#: own field and overwrite it with today's date.
_DATE_LINE_PATTERN = re.compile(
    r"^([ \t]*)(Tarih)([ \t]*:[ \t]*)\[[^\]]*\][ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


def fill_date_placeholders(draft: str, today: str) -> NormalizedDraft:
    """Fill the draft's own "Tarih:" placeholder with the server-resolved date.

    A generated draft must never leave its own date for the human to supply
    (see app.ai.workflows.dates.today_tr and the bug report item this
    closes) -- the writer is told to copy `today` verbatim into this line
    (see draft_graph._build_brief's section 0), but a prompt instruction is
    not a guarantee, so this is the deterministic backstop, run right after
    ``normalize_unfilled_markers`` so a model that wrote "belirtilmemiş"
    instead of a placeholder is caught first and this still finds a
    placeholder to fill.

    Args:
        draft: The generated draft text.
        today: The date to substitute (see app.ai.workflows.dates.today_tr).

    Returns:
        The (possibly rewritten) draft, and how many "Tarih:" lines were
        filled. When ``today`` is empty, the draft is returned unchanged --
        there is nothing to fill with, and leaving the placeholder in place
        is safer than writing an empty value into it.
    """
    if not today:
        return NormalizedDraft(text=draft, substitutions=0)

    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        indent, label, separator = match.groups()
        count += 1
        return f"{indent}{label}{separator}{today}"

    filled = _DATE_LINE_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=filled, substitutions=count)


#: A bare, role-less placeholder the writer left, mapped to the version
#: that states whose it is -- for the ordinary (institutional) draft. Keyed
#: on the folded ("ünvan"/"Ünvan"/"UNVAN" all collapse to "unvan") form so
#: this catches every casing/accent variant the model might emit, matching
#: how `writer.md` itself now names these fields (see its own "İmza Bloğu"
#: rule) -- this is the deterministic backstop for when a prompt
#: instruction alone wasn't enough, same role `normalize_unfilled_markers`
#: plays for the header block's own fields.
_SIGNATURE_PLACEHOLDERS: dict[str, str] = {
    _fold("Ad Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Ad, Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Soyad"): "İmzalayacak yetkilinin adı ve soyadı",
    _fold("Unvan"): "İmzalayacak yetkilinin unvanı",
    _fold("İmza"): "İmzalayacak yetkilinin adı ve soyadı",
}

#: Same placeholders, for an individual dilekçe (see `writer.md`'s own
#: "Yapı İstisnaları" section) -- there is no "yetkili" signing on behalf of
#: an institution, only the petitioner themselves.
_SIGNATURE_PLACEHOLDERS_PETITION: dict[str, str] = {
    _fold("Ad Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Ad, Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Soyad"): "Dilekçe sahibinin adı ve soyadı",
    _fold("Unvan"): "Dilekçe sahibinin unvanı",
    _fold("İmza"): "Dilekçe sahibinin adı ve soyadı",
}

#: A bare institution placeholder -- always the sender's own institution
#: (see `writer.md`'s "1. Başlık / Kurum Adı" rule): the only "Kurum Adı"
#: a draft's own antet ever refers to is whoever is sending it, never the
#: addressee (that name lives behind "Muhatap", not this label).
_INSTITUTION_PLACEHOLDERS: dict[str, str] = {
    _fold("Kurum Adı"): "Gönderen kurumun adı",
}


def normalize_role_placeholders(
    draft: str, *, is_individual_petition: bool = False
) -> NormalizedDraft:
    """Rewrite an ambiguous, role-less placeholder into one that states whose it is.

    The bug this closes: a bare ``[Ad Soyad]``/``[Unvan]`` placeholder gives
    the human gate nothing to ask *about* -- ``missing_info.
    InfoQuestion.to_prompt_question`` renders whatever text sits inside the
    brackets verbatim as the question's own label, so an unattributed
    placeholder becomes an unattributed question ("'Ad Soyad' bilgisi
    nedir?" -- whose?).

    Deliberately position-independent (unlike, say, ``_DATE_LINE_PATTERN``,
    which is anchored to the draft's own "Tarih:" line specifically): a
    bare "Ad Soyad"/"Unvan"/"İmza" placeholder is, in this domain, always
    about who is signing, and a bare "Kurum Adı" is always about who is
    sending, regardless of where in the draft the writer happened to leave
    it -- there is no second, different thing either phrase could
    plausibly mean here.

    Args:
        draft: The generated draft text.
        is_individual_petition: True for a personal dilekçe-shaped sub-genre
            (see ``draft_verifier.verify_draft``'s own parameter of the same
            name) -- selects "Dilekçe sahibinin..." over "İmzalayacak
            yetkilinin...".

    Returns:
        The (possibly rewritten) draft, and how many placeholders were
        renamed.
    """
    signature_map = _SIGNATURE_PLACEHOLDERS_PETITION if is_individual_petition else _SIGNATURE_PLACEHOLDERS
    count = 0

    def _replace(match: "re.Match[str]") -> str:
        nonlocal count
        inner = match.group(0)[1:-1].strip()
        folded = _fold(inner)
        replacement = signature_map.get(folded) or _INSTITUTION_PLACEHOLDERS.get(folded)
        if replacement is None:
            return match.group(0)
        count += 1
        return f"[{replacement}]"

    normalized = PLACEHOLDER_PATTERN.sub(_replace, draft)
    return NormalizedDraft(text=normalized, substitutions=count)
