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

logger = logging.getLogger(__name__)


class InfoQuestion(BaseModel):
    """A single piece of information the human needs to supply."""

    key: str = Field(description="Stable slug identifying this placeholder across resume calls.")
    label: str = Field(description="The placeholder text shown to the user, verbatim from the draft.")
    why: str = Field(default="", description="Legal/regulatory justification, when known.")
    example: str | None = Field(default=None, description="An example value, when one is obvious.")
    required: bool = Field(default=True)


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

    for match in PLACEHOLDER_PATTERN.findall(draft):
        placeholder_text = match.strip("[]").strip()
        if not placeholder_text:
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


def apply_answers(draft: str, answers: dict[str, str]) -> tuple[str, list[str]]:
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
        answer = (answers.get(key) or "").strip()
        if answer:
            return answer
        residual.append(key)
        return match.group(0)

    substituted = PLACEHOLDER_PATTERN.sub(_replace, draft)
    if residual:
        logger.info("apply_answers left %d placeholder(s) unfilled.", len(residual))
    return substituted, residual
