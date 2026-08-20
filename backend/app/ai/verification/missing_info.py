"""Turn a draft's unfilled placeholders into a human-answerable request.

Deterministic and LLM-free on purpose: the missing-information request is the
HITL trigger for Görev 2's "gerekli durumlarda eksik bilgi talep edebilmesi"
requirement, and it must produce the same questions for the same draft every
time -- including on the resume path, where nothing regenerates the draft.
"""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, VerificationReport, _fold
from app.ai.verification.placeholders import _DATE_LINE_PATTERN
from app.ai.workflows.writing_brief import AUTO_ANSWER

logger = logging.getLogger(__name__)


class InfoQuestion(BaseModel):
    """A single piece of information the human needs to supply."""

    key: str = Field(description="Stable slug identifying this placeholder across resume calls.")
    label: str = Field(description="The placeholder text shown to the user, verbatim from the draft.")
    why: str = Field(default="", description="Legal/regulatory justification, when known.")
    example: str | None = Field(default=None, description="An example value, when one is obvious.")
    required: bool = Field(default=True)

    def to_prompt_question(self) -> dict[str, Any]:
        """Convert to the canonical ``PromptQuestion`` shape for the emit boundary.

        ``InfoQuestion`` stays the type used everywhere internally --
        ``apply_answers``/``_slugify`` and the resume contract all key off
        ``key`` -- this only runs at ``human_gate_node``'s emit call, so one
        frontend card component can render this alongside the writing-brief
        and clarify questions. ``key`` is carried through byte-for-byte: it
        is the join key ``apply_answers`` substitutes placeholders by.
        """
        return {
            "key": self.key,
            "question": f"'{self.label}' bilgisi nedir?",
            "header": self.label,
            "help": self.why,
            "example": self.example,
            "options": [],
            "multi_select": False,
            "allow_free_text": True,
            "required": self.required,
        }


def _slugify(text: str) -> str:
    """Fold placeholder text into a stable, reproducible answer key."""
    slug = _fold(text).replace(" ", "_")
    return slug or "bilgi"


def _match_missing_field(
    label_text: str, missing_fields: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Find the compliance-node MissingField this placeholder most likely refers to."""
    folded_label = _fold(label_text)
    if not folded_label:
        return None
    for field in missing_fields:
        field_label = _fold(str(field.get("label", "")))
        field_key = _fold(str(field.get("key", "")))
        if field_label and (field_label in folded_label or folded_label in field_label):
            return field
        if field_key and field_key in folded_label:
            return field
    return None


def build_missing_info_request(
    draft: str,
    report: VerificationReport,
    classification: dict[str, Any] | None = None,
) -> list[InfoQuestion]:
    """Build one question per distinct ``[...]`` placeholder in a draft.

    Args:
        draft: The generated draft text.
        report: The deterministic verification report (unused directly today,
            kept in the signature so a future structural check can gate which
            placeholders are actually asked about without changing callers).
        classification: The analysis result; its ``missing_fields`` supply the
            ``why`` justification when a placeholder matches one.

    Returns:
        One :class:`InfoQuestion` per distinct placeholder, in draft order.
    """
    del report  # reserved for a future structural gate; not needed today
    missing_fields = (classification or {}).get("missing_fields") or []
    seen: dict[str, InfoQuestion] = {}

    # The response's own "Tarih:" header line is the one placeholder that
    # is never a real information gap: app.ai.verification.placeholders.
    # fill_date_placeholders already tried to substitute it with the
    # server-resolved date before this runs (see draft_graph.verify_node /
    # revise_graph.verify_node), so asking about it would ask the user for
    # a fact the system, not the user, is responsible for. Anchored to the
    # exact same structural line `_DATE_LINE_PATTERN` matches -- NOT a bare
    # "folded text starts with tarih" substring test, which this used to be:
    # that also silently swallowed unrelated date-labelled placeholders
    # (e.g. "[Başvuru Tarihi]", "[Son Başvuru Tarihi]", inline "[Tarih
    # Aralığı]") into never being asked about at all, while apply_answers
    # -- which has no such skip -- still counted the very same placeholder
    # as unanswered ("residual") on resume. The two disagreeing produced a
    # NEEDS_INPUT round whose `missing_information` list was empty: an
    # interrupt with zero questions in it, which the human has no way to
    # answer and the gate has no way to leave (see human_gate_node's own
    # `residual_questions` filter, the other half of this fix).
    date_header_spans = [match.span() for match in _DATE_LINE_PATTERN.finditer(draft)]

    def _is_date_header(match: "re.Match[str]") -> bool:
        return any(
            start <= match.start() and match.end() <= end
            for start, end in date_header_spans
        )

    for match in PLACEHOLDER_PATTERN.finditer(draft):
        placeholder_text = match.group(0).strip("[]").strip()
        if not placeholder_text:
            continue
        if _is_date_header(match):
            continue
        key = _slugify(placeholder_text)
        if key in seen:
            continue

        field = _match_missing_field(placeholder_text, missing_fields)
        why = ""
        if field:
            why = f"{field.get('mevzuat', '')} -- {field.get('reason', '')}".strip(" -")

        seen[key] = InfoQuestion(key=key, label=placeholder_text, why=why)

    return list(seen.values())


def _coerce_answer(value: object) -> str:
    """Flatten a resume answer to a string, joining a multi-select list.

    ``ChatResumeRequest.answers`` widened to ``dict[str, str | list[str]]``
    to carry a multi_select PromptQuestion's answer (see
    app.ai.workflows.event_schema.PromptQuestion) -- no missing-information
    question is multi_select today, but this keeps ``apply_answers`` correct
    if that ever changes, joined plainly rather than via a hidden delimiter
    that could leak into the substituted placeholder text.
    """
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")


def apply_answers(draft: str, answers: dict[str, Any]) -> tuple[str, list[str]]:
    """Substitute answered placeholders back into the draft without regenerating it.

    Args:
        draft: The draft text, containing ``[...]`` placeholders.
        answers: Answers keyed by the :class:`InfoQuestion` ``key`` this draft
            produced.

    Returns:
        The substituted draft and the list of placeholder keys still unfilled.
    """
    residual: list[str] = []

    def _replace(match: "re.Match[str]") -> str:
        placeholder_text = match.group(0).strip("[]").strip()
        key = _slugify(placeholder_text)
        raw_answer = answers.get(key)
        if raw_answer == AUTO_ANSWER:
            # "Sen karar ver" ("acceptAllDefaults" in the frontend) --
            # the user explicitly declined to supply this value, so this is
            # neither a real answer (never substitute the sentinel's own
            # literal text into the letter) nor an unanswered question to
            # re-ask (never append to `residual`, which would reopen the
            # very round the user just tried to close). Leave the bracketed
            # placeholder exactly as the writer left it -- a visible,
            # in-text marker a human reviewer can still see, the same
            # convention `writer.md`'s own `[BİLGİ EKSİK: ...]` placeholders
            # use, not silently swallowed or replaced with garbage text.
            return match.group(0)
        answer = _coerce_answer(raw_answer).strip()
        if answer:
            return answer
        residual.append(key)
        return match.group(0)

    substituted = PLACEHOLDER_PATTERN.sub(_replace, draft)
    if residual:
        logger.info("apply_answers left %d placeholder(s) unfilled.", len(residual))
    return substituted, residual
