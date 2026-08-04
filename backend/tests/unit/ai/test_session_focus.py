"""Unit tests for SessionFocus's pure update logic and merge reducer.

SessionFocus is the one PlanningState channel planning_node must never
reset -- these tests exercise compute_focus_update/merge_focus directly
(no compiled graph needed) to prove the accumulation and versioning rules
independent of the graph wiring.
"""

from app.ai.session.focus import (
    OBJECTIVE_CHAR_CAP,
    DraftVersion,
    SessionFocus,
    compute_focus_update,
    merge_focus,
)


def test_a_draft_intent_turn_seeds_the_objective():
    focus = SessionFocus()

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Bu evraka cevap yazısı hazırla.",
        draft_result={},
    )

    assert update["objective"] == "Bu evraka cevap yazısı hazırla."


def test_the_objective_accumulates_across_turns():
    focus = SessionFocus(objective="Bir cevap yazısı hazırla.")

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Valiliğe hitaben olsun.",
        draft_result={},
    )

    assert update["objective"] == "Bir cevap yazısı hazırla. | Valiliğe hitaben olsun."


def test_the_objective_is_capped_and_drops_the_oldest_fragment():
    focus = SessionFocus(objective="x" * (OBJECTIVE_CHAR_CAP - 5))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="y" * 20,
        draft_result={},
    )

    assert len(update["objective"]) == OBJECTIVE_CHAR_CAP
    # The newest fragment survives whole; it is the front that gets trimmed.
    assert update["objective"].endswith("y" * 20)


def test_assist_and_greeting_intents_do_not_touch_the_objective():
    focus = SessionFocus(objective="Mevcut hedef.")

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="assist",
        input_text="Merhaba, nasılsın?",
        draft_result={},
    )

    assert "objective" not in update
    assert update["last_intent"] == "assist"


def test_a_blank_message_does_not_change_the_objective():
    focus = SessionFocus(objective="Mevcut hedef.")

    update = compute_focus_update(
        focus, document_id=None, plan_intent="draft", input_text="   ", draft_result={}
    )

    assert update["objective"] == "Mevcut hedef."


def test_a_completed_draft_becomes_the_first_version():
    focus = SessionFocus()

    update = compute_focus_update(
        focus,
        document_id="doc-1",
        plan_intent="draft",
        input_text="Cevap yazısı hazırla.",
        draft_result={
            "status": "COMPLETED",
            "draft": "Sayın Makam, ...",
            "correspondence_type": "cover_letter",
            "combined_score": 82.0,
        },
    )

    version = update["active_draft"]
    assert version.version == 1
    assert version.text == "Sayın Makam, ..."
    assert version.created_from == "draft"
    assert update["draft_history"] == (version,)


def test_a_second_settled_draft_is_recorded_as_a_revise_not_a_fresh_draft():
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Daha resmi yap.",
        draft_result={
            "status": "COMPLETED",
            "draft": "v2",
            "correspondence_type": "cover_letter",
            "combined_score": 90.0,
        },
    )

    version = update["active_draft"]
    assert version.version == 2
    assert version.created_from == "revise"
    assert update["draft_history"] == (first, version)


def test_a_revise_requested_or_rejected_draft_does_not_become_a_version():
    focus = SessionFocus()

    for status in ("REVISE_REQUESTED", "REJECTED", "FAILED", "IN_PROGRESS"):
        update = compute_focus_update(
            focus,
            document_id=None,
            plan_intent="draft",
            input_text="x",
            draft_result={"status": status, "draft": "..."},
        )
        assert "active_draft" not in update, status


def test_no_draft_step_this_turn_leaves_the_draft_fields_untouched():
    update = compute_focus_update(
        SessionFocus(),
        document_id=None,
        plan_intent="assist",
        input_text="soru",
        draft_result={},
    )

    assert "active_draft" not in update
    assert "draft_history" not in update


def test_merge_focus_applies_a_partial_update_onto_the_existing_value():
    base = SessionFocus(active_document_id="doc-1", objective="hedef")

    merged = merge_focus(base, {"objective": "yeni hedef"})

    assert merged.active_document_id == "doc-1"
    assert merged.objective == "yeni hedef"


def test_merge_focus_starts_from_a_fresh_focus_when_left_is_none():
    merged = merge_focus(None, {"active_document_id": "doc-1"})

    assert merged == SessionFocus(active_document_id="doc-1")


def test_merge_focus_is_a_no_op_for_an_empty_update():
    base = SessionFocus(objective="hedef")

    assert merge_focus(base, {}) == base
    assert merge_focus(base, None) == base
