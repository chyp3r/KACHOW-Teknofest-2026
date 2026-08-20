"""Unit tests for planning_graph._deterministic_handoff_target -- the free,
deterministic re-score that catches a fallback "assist" decision missing
decisive draft/revise evidence (Faz 7).
"""

from app.ai.session.focus import DraftVersion, SessionFocus
from app.ai.workflows.planning_graph import _deterministic_handoff_target


def _draft_version(**overrides) -> DraftVersion:
    defaults = dict(
        version=1, text="Konu: Test\n\nArz ederim.", correspondence_type="response_letter",
        confidence_score=90.0, created_from="draft",
    )
    defaults.update(overrides)
    return DraftVersion(**defaults)


def test_a_clear_drafting_request_is_found_even_without_focus():
    state = {"input_text": "Bu evraka bir cevap yazısı hazırla.", "document_id": None}
    assert _deterministic_handoff_target(state) == "draft"


def test_a_conversational_message_finds_no_handoff_target():
    state = {"input_text": "Merhaba, nasılsın?", "document_id": None}
    assert _deterministic_handoff_target(state) is None


def test_a_revision_request_is_found_when_a_draft_is_active():
    state = {
        "input_text": "Kapanışı 'Arz ederim' yerine 'Rica ederim' yap.",
        "document_id": None,
        "focus": SessionFocus(active_draft=_draft_version()),
    }
    assert _deterministic_handoff_target(state) == "revise"


def test_a_revision_request_never_wins_without_an_active_draft():
    """C-item: revise is never handed off to without an active draft --
    score_intents itself gates every revise rule on has_active_draft, so
    this must come back None (or, if the same text also reads as a draft
    request, "draft") rather than "revise"."""
    state = {
        "input_text": "Kapanışı 'Arz ederim' yerine 'Rica ederim' yap.",
        "document_id": None,
        "focus": SessionFocus(),
    }
    assert _deterministic_handoff_target(state) != "revise"


def test_an_empty_message_finds_no_handoff_target():
    state = {"input_text": "", "document_id": None}
    assert _deterministic_handoff_target(state) is None
