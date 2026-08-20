"""A deterministic, LLM-free change log for a revision.

The user should be able to see *what actually changed* without reading the
full before/after draft side by side. This is a plain paragraph-level diff
(``difflib.SequenceMatcher``) between the draft before and after a revision
-- no model call, no interpretation, just what moved, what was added and
what was removed. Attribution to the instruction's own directives (see
``app.ai.revision.instruction``) is best-effort positional matching, shown
as a hint, not a claim of certainty.
"""

import difflib
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from app.ai.revision.instruction import EditDirective

#: Before/after snippets are truncated to this length -- a changelog entry is
#: meant to say "this paragraph changed", not reproduce the whole paragraph a
#: second time.
_SNIPPET_LIMIT = 400

#: `ChangeEntry.directive`'s own `max_length` -- kept as its own constant
#: (rather than reusing `_SNIPPET_LIMIT`) so the truncation applied before
#: construction and the field's own validation limit can never drift apart
#: silently. `EditDirective.raw` (the source of this value on the
#: whole-draft fallback path -- see `instruction.decompose_instruction`) is
#: itself unbounded: it carries the user's entire revision instruction
#: verbatim, unlike every other `EditDirective` field, which `_parse_one`
#: derives from short, closed vocabularies. An instruction longer than this
#: used to reach `ChangeEntry(...)` untruncated and raise a
#: `pydantic.ValidationError` `audit_node` never caught -- discarding an
#: already-successful revision over a changelog attribution failure (see
#: `revise_graph.audit_node`'s own hardening for the other half of this
#: fix).
_DIRECTIVE_LIMIT = 200


class ChangeEntry(BaseModel):
    """One paragraph-level change between two draft versions."""

    directive: str = Field(
        default="", max_length=_DIRECTIVE_LIMIT,
        description="En yakın eşleşen kullanıcı direktifi (varsa), en iyi çaba eşleştirmesi.",
    )
    scope: str = Field(default="", description="Direktifin kapsamı (paragraph/section/whole).")
    before: str = Field(default="", max_length=_SNIPPET_LIMIT)
    after: str = Field(default="", max_length=_SNIPPET_LIMIT)
    char_delta: int = Field(description="after uzunluğu eksi before uzunluğu.")


class RevisionChangelog(BaseModel):
    """The full change log for one revision, oldest change first."""

    entries: list[ChangeEntry] = Field(default_factory=list)
    summary: str = Field(default="")


def _truncate(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _summarize(entries: list[ChangeEntry]) -> str:
    if not entries:
        return "Taslakta gözle görülür bir değişiklik tespit edilmedi."
    added = sum(1 for e in entries if not e.before and e.after)
    removed = sum(1 for e in entries if e.before and not e.after)
    changed = len(entries) - added - removed
    parts = []
    if changed:
        parts.append(f"{changed} bölüm değiştirildi")
    if added:
        parts.append(f"{added} bölüm eklendi")
    if removed:
        parts.append(f"{removed} bölüm kaldırıldı")
    return ", ".join(parts) + "."


def build_changelog(
    before: str,
    after: str,
    directives: Optional[Sequence[EditDirective]] = None,
) -> RevisionChangelog:
    """Diff two draft versions at paragraph granularity.

    Args:
        before: The draft text before this revision.
        after: The draft text after this revision.
        directives: The instruction's own directives, in order, for
            best-effort attribution -- the ``i``-th changed paragraph group
            is labeled with the ``i``-th directive's ``raw`` text when one
            exists, purely as a hint for the reader; no correctness is
            claimed about which directive actually caused which change
            (a single directive can touch several paragraphs, or none).

    Returns:
        The change log, oldest change first.
    """
    before_paragraphs = _split_paragraphs(before)
    after_paragraphs = _split_paragraphs(after)
    directive_texts = [d.raw for d in (directives or [])]
    directive_scopes = [d.scope for d in (directives or [])]

    matcher = difflib.SequenceMatcher(None, before_paragraphs, after_paragraphs, autojunk=False)
    entries: list[ChangeEntry] = []
    directive_index = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        before_text = "\n\n".join(before_paragraphs[i1:i2])
        after_text = "\n\n".join(after_paragraphs[j1:j2])
        directive = directive_texts[directive_index] if directive_index < len(directive_texts) else ""
        scope = directive_scopes[directive_index] if directive_index < len(directive_scopes) else ""
        directive_index += 1

        entries.append(
            ChangeEntry(
                directive=_truncate(directive, _DIRECTIVE_LIMIT),
                scope=scope,
                before=_truncate(before_text),
                after=_truncate(after_text),
                char_delta=len(after_text) - len(before_text),
            )
        )

    return RevisionChangelog(entries=entries, summary=_summarize(entries))
