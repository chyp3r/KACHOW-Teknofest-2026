"""Deterministic parsing of a user's revision request.

A revise turn never re-classifies and never re-retrieves legislation by
default (see ``app.ai.workflows.revise``) -- it operates directly on the
active draft, the text the user already saw. This module is the first,
LLM-free step: turning the user's raw instruction into a structured
``RevisionInstruction`` that later steps (targeting, conditional
re-retrieval, conflict auditing) all read from, without re-parsing the raw
text themselves.

The user's instruction is never rewritten or softened here -- ``raw`` is
carried forward verbatim into every downstream prompt. This module only
adds structure *around* it; it never edits it.
"""

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.ai.verification.draft_verifier import (
    AMOUNT_PATTERN,
    DATE_PATTERN,
    DOCUMENT_NUMBER_PATTERN,
    INSTITUTION_PATTERN,
    LEGISLATION_PATTERN,
)
from app.ai.workflows.intent_scorer import normalize

Scope = Literal["paragraph", "section", "whole"]
Operation = Literal["tone_formal", "tone_informal", "shorten", "lengthen", "content"]

#: Recognized structural parts of the fixed 9-part official letter format
#: (see prompts/templates/writer.md) and the phrases that name them.
_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "konu": ("konu",),
    "giris": ("giris", "ilk paragraf", "baslangic paragrafi"),
    "kapanis": ("kapanis", "son paragraf", "arz kismi", "rica kismi"),
    "imza": ("imza", "imza blogu", "imza kismi"),
}

#: Phrases inside the *closing* paragraph specifically -- used to locate the
#: "kapanış" section structurally rather than just by position, since a
#: closing sentence can appear mid-paragraph rather than alone on one.
_CLOSING_MARKERS = ("arz ederim", "rica ederim", "bilgilerinize sunulur")

_ORDINAL_PATTERN = re.compile(r"(\d+)\s*\.?\s*paragraf")
_ORDINAL_WORDS: dict[str, int] = {
    "ilk": 1, "birinci": 1, "ikinci": 2, "ucuncu": 3, "dorduncu": 4, "son": -1,
}

_OPERATION_HINTS: dict[Operation, tuple[str, ...]] = {
    "tone_formal": ("daha resmi", "resmiyet"),
    "tone_informal": ("daha samimi", "daha sicak"),
    "shorten": ("kisalt", "daha kisa", "ozetle"),
    "lengthen": ("uzat", "daha uzun", "detaylandir", "genislet"),
}

#: Splits a compound instruction into per-clause fragments for
#: ``decompose_instruction``. Turkish coordinators plus the usual clause
#: terminators -- deliberately narrow (a false split just produces one extra
#: fragment that fails to parse into a directive and gets dropped, see
#: ``decompose_instruction``; a missed split falls back to whole-draft scope,
#: today's existing safe default).
_CLAUSE_SPLIT = re.compile(
    r"\s+ve\s+|\s+ayrıca\s+|\s+bir de\s+|\s*;\s*|\n+|(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])"
)

#: Claim kinds whose presence in an instruction means it is trying to
#: introduce or reference normative content (a law, an institution, a
#: document number, an amount) rather than just ask for a style/length
#: change -- see ``needs_reretrieval``.
_NORMATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    LEGISLATION_PATTERN,
    INSTITUTION_PATTERN,
    DOCUMENT_NUMBER_PATTERN,
    DATE_PATTERN,
    AMOUNT_PATTERN,
)


@dataclass(frozen=True)
class EditDirective:
    """One atomic edit extracted from a (possibly compound) instruction.

    Attributes:
        scope: What part of the draft this directive targets.
        operation: What kind of change it asks for. Informational only.
        section_hint: A recognized structural part name, when
            ``scope == "section"``.
        ordinal: A 1-based paragraph index (``-1`` means "last"), when
            ``scope == "paragraph"``.
        raw: This directive's own clause, unmodified.
        order: Position among the instruction's directives, for stable
            right-to-left application (see ``locate_target``'s caller).
    """

    scope: Scope
    operation: Operation
    section_hint: Optional[str]
    ordinal: Optional[int]
    raw: str
    order: int


@dataclass(frozen=True)
class RevisionInstruction:
    """The user's revise request, parsed into a scope and an operation.

    Attributes:
        scope: What part of the draft the instruction targets.
        operation: What kind of change it asks for. Informational only --
            it does not change which prompt runs, only what a caller might
            log or show; the model reads ``raw`` directly.
        section_hint: A recognized structural part name (see
            ``_SECTION_HINTS``), when ``scope == "section"``.
        ordinal: A 1-based paragraph index (``-1`` means "last"), when
            ``scope == "paragraph"``.
        raw: The instruction text, unmodified, for the prompt.
        directives: The instruction decomposed into its atomic edits (see
            ``decompose_instruction``). Always at least one entry, whose
            ``raw`` is the full instruction when it could not be split
            further -- the same safe default ``scope="whole"`` represents.
        introduces_normative_content: Whether the instruction references a
            law, article, institution, document number, date or amount --
            i.e. asks for something a re-retrieval of legislation might be
            needed to ground (see ``needs_reretrieval``).
        normative_tokens: The specific tokens that made
            ``introduces_normative_content`` true.
    """

    scope: Scope
    operation: Operation
    section_hint: Optional[str]
    ordinal: Optional[int]
    raw: str
    directives: tuple[EditDirective, ...] = field(default_factory=tuple)
    introduces_normative_content: bool = False
    normative_tokens: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TargetSpan:
    """A char range in the draft the rewrite should be confined to."""

    start: int
    end: int
    text: str


def _parse_one(raw: str) -> tuple[Scope, Operation, Optional[str], Optional[int]]:
    """Extract scope/operation/section_hint/ordinal from a single clause."""
    normalized = normalize(raw)

    section_hint: Optional[str] = None
    for canonical, surfaces in _SECTION_HINTS.items():
        if any(surface in normalized for surface in surfaces):
            section_hint = canonical
            break

    ordinal: Optional[int] = None
    match = _ORDINAL_PATTERN.search(normalized)
    if match:
        ordinal = int(match.group(1))
    else:
        padded = f" {normalized} "
        for word, value in _ORDINAL_WORDS.items():
            if f" {word} paragraf" in padded:
                ordinal = value
                break

    operation: Operation = "content"
    for op, surfaces in _OPERATION_HINTS.items():
        if any(surface in normalized for surface in surfaces):
            operation = op
            break

    if ordinal is not None:
        scope: Scope = "paragraph"
    elif section_hint is not None:
        scope = "section"
    else:
        scope = "whole"

    return scope, operation, section_hint, ordinal


def _normative_tokens(text: str) -> tuple[str, ...]:
    """Every normative-content token (law/madde/institution/date/amount) in
    ``text``, de-duplicated but order-preserving."""
    seen: dict[str, None] = {}
    for pattern in _NORMATIVE_PATTERNS:
        for match in pattern.findall(text):
            value = (match if isinstance(match, str) else match[0]).strip()
            if value:
                seen.setdefault(value, None)
    return tuple(seen)


def decompose_instruction(instruction: str) -> tuple[EditDirective, ...]:
    """Split a compound instruction into its atomic edit directives.

    Args:
        instruction: The user's raw revise request, possibly asking for
            several distinct changes at once ("Konuyu değiştir ve son
            paragrafı kısalt.").

    Returns:
        One ``EditDirective`` per recognized clause. A clause that names
        neither a section nor a paragraph and has no operation surface is
        dropped as noise (a coordinator by itself, e.g. a stray "ve"). When
        that leaves zero or one directive, a single ``scope="whole"``
        directive carrying the *entire* original instruction is returned
        instead -- decomposition is a targeting optimization, not something
        callers should ever have to special-case when it finds nothing to
        split.
    """
    fragments = [frag.strip() for frag in _CLAUSE_SPLIT.split(instruction) if frag.strip()]

    directives: list[EditDirective] = []
    for order, fragment in enumerate(fragments):
        scope, operation, section_hint, ordinal = _parse_one(fragment)
        if scope == "whole" and operation == "content":
            # Neither a location nor an operation was recognized in this
            # fragment alone -- not a directive, just connective tissue.
            continue
        directives.append(
            EditDirective(
                scope=scope, operation=operation, section_hint=section_hint,
                ordinal=ordinal, raw=fragment, order=order,
            )
        )

    if len(fragments) > 1 and len(directives) < len(fragments):
        # At least one coordinator-separated clause named neither a
        # section/paragraph nor an operation -- e.g. "muhatap Ankara
        # Valiliği" in "Konuyu değiştir ve muhatap Ankara Valiliği". That
        # clause cannot ride along inside another directive's own located
        # span (a directive's prompt is confined to its own span -- see
        # _build_directive_prompt), so it would otherwise be silently
        # dropped: this was Görev 2's "bilgi kısmı hiçbir yere yazılmıyor"
        # bug. Re-parsing the *combined* text for a single section_hint
        # (the old fallback below) is not a fix either -- it can rediscover
        # a narrow location from just one clause and misapply the whole
        # compound ask to that one span. Safe default: a multi-clause
        # instruction that does not fully decompose into located directives
        # falls back to one whole-draft rewrite, carrying every clause's
        # own text (`instruction`, unmodified) so nothing asked for is lost.
        return (
            EditDirective(
                scope="whole", operation="content", section_hint=None,
                ordinal=None, raw=instruction, order=0,
            ),
        )

    if len(directives) <= 1:
        scope, operation, section_hint, ordinal = _parse_one(instruction)
        return (
            EditDirective(
                scope=scope, operation=operation, section_hint=section_hint,
                ordinal=ordinal, raw=instruction, order=0,
            ),
        )

    return tuple(directives)


def parse_revision_instruction(instruction: str) -> RevisionInstruction:
    """Extract a scope and an operation from a revise request.

    Deterministic keyword matching over the draft's own known, fixed
    structure -- not a general NLU parse. An instruction naming neither a
    paragraph number nor a recognized section resolves to ``scope="whole"``,
    which is the safe default: a full, still single-call rewrite rather than
    a guess at which part was meant.

    Args:
        instruction: The user's revise request.

    Returns:
        The parsed instruction, including its decomposition into atomic
        directives and whether it references normative content.
    """
    scope, operation, section_hint, ordinal = _parse_one(instruction)
    tokens = _normative_tokens(instruction)

    return RevisionInstruction(
        scope=scope, operation=operation, section_hint=section_hint,
        ordinal=ordinal, raw=instruction,
        directives=decompose_instruction(instruction),
        introduces_normative_content=bool(tokens),
        normative_tokens=tokens,
    )


def needs_reretrieval(instruction: RevisionInstruction) -> bool:
    """Whether this revision should trigger a fresh legislation lookup.

    True when the instruction itself names a law, article, institution,
    date or amount that the draft's frozen context may not already cover --
    a pure tone/length request never does. See
    ``app.ai.revision.retrieval.maybe_extend_context``, the only caller.

    Args:
        instruction: The parsed instruction.

    Returns:
        Whether a conditional re-retrieval should run.
    """
    return instruction.introduces_normative_content


def _split_paragraphs(draft: str) -> list[tuple[int, int]]:
    """Return (start, end) char offsets of each blank-line-separated paragraph."""
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", draft)]


#: The draft's own fixed metadata-header field labels (see writer.md's
#: numbered structure, fields 2-6: Sayı/Tarih/Konu/Muhatap/İlgi/Ekler) --
#: same label set app.ai.verification.placeholders._HEADER_LINE_PATTERN
#: recognises for its own, unrelated backstop, extended with İlgi/Ekler
#: since those two can also sit on the same header block.
_HEADER_FIELD_LINE = re.compile(
    r"^\s*(Sayı|Sayi|Tarih|Konu|Muhatap|İlgi|Ilgi|Ekler)\s*:", re.IGNORECASE
)


def _is_header_paragraph(text: str) -> bool:
    """Whether a blank-line-separated block is pure letter metadata, never
    something a user means by "ilk paragraf"/"giriş".

    The bug this closes: a typical draft's "Konu:"/"Sayı:"/"Tarih:" lines
    sit on consecutive lines with *no* blank line between them (see
    writer.md's fixed structure), so ``_split_paragraphs`` groups them into
    one block that -- unfiltered -- lands at index 0, exactly where "1.
    paragrafı sil"/"girişi değiştir" naturally point. Nobody asking to edit
    a letter's opening means its metadata header; unfiltered, the reviser
    was handed that block as its own rewrite target for an unrelated body
    edit and, applying it to a "Sayı: ..." line instead of prose, would as
    often as not mangle or drop it outright -- the concrete "sayıyı siliyor"
    symptom this closes. A leading antet block ("T.C.\\nKURUM ADI", no
    labelled field at all) is caught the same way, via the literal "T.C."
    marker every antet starts with.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.upper().startswith("T.C."):
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(_HEADER_FIELD_LINE.match(line) for line in lines)


def _body_paragraphs(draft: str, paragraphs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """``paragraphs`` with any pure-metadata block dropped, for ordinal/
    "giriş" targeting only -- ``konu``/``kapanis``/``imza`` section hints
    keep scanning the full list unfiltered, since ``konu`` specifically
    means to find the header's own Konu line."""
    body = [span for span in paragraphs if not _is_header_paragraph(draft[span[0] : span[1]])]
    return body or paragraphs


def _locate_one(
    draft: str, paragraphs: list[tuple[int, int]], *,
    scope: Scope, section_hint: Optional[str], ordinal: Optional[int],
) -> Optional[TargetSpan]:
    if scope == "paragraph" and ordinal is not None:
        body = _body_paragraphs(draft, paragraphs)
        index = ordinal - 1 if ordinal > 0 else len(body) - 1
        if 0 <= index < len(body):
            start, end = body[index]
            return TargetSpan(start, end, draft[start:end])
        return None

    if scope == "section" and section_hint:
        if section_hint == "imza":
            start, end = paragraphs[-1]
            return TargetSpan(start, end, draft[start:end])
        if section_hint == "kapanis":
            for start, end in paragraphs:
                if any(marker in normalize(draft[start:end]) for marker in _CLOSING_MARKERS):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if section_hint == "konu":
            for start, end in paragraphs:
                if normalize(draft[start:end]).startswith("konu"):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if section_hint == "giris":
            body = _body_paragraphs(draft, paragraphs)
            start, end = body[0]
            return TargetSpan(start, end, draft[start:end])

    return None


def locate_target(
    draft: str, instruction: "RevisionInstruction | EditDirective"
) -> Optional[TargetSpan]:
    """Find the char span ``instruction`` targets, if it names one precisely.

    Args:
        draft: The current draft text.
        instruction: The parsed instruction or a single directive from it --
            both carry the same ``scope``/``section_hint``/``ordinal`` triple.

    Returns:
        The target span, or ``None`` when the scope is ``"whole"`` or the
        named paragraph/section can't be located -- callers treat ``None``
        as "rewrite the whole draft" rather than guessing.
    """
    paragraphs = _split_paragraphs(draft)
    if not paragraphs:
        return None
    return _locate_one(
        draft, paragraphs,
        scope=instruction.scope, section_hint=instruction.section_hint,
        ordinal=instruction.ordinal,
    )


def _merge(source_draft: str, target: Optional[TargetSpan], rewritten: str) -> str:
    """Splice the rewritten text back in. The untouched head and tail come
    straight from the original text rather than being reproduced by the
    model, so an unintended change outside the target span is structurally
    impossible rather than merely something to check for afterward."""
    rewritten = rewritten.strip()
    if target is None:
        return rewritten
    return f"{source_draft[:target.start]}{rewritten}{source_draft[target.end:]}"
