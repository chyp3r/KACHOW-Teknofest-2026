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


def test_a_fresh_brief_step_overwrites_a_stale_writing_brief():
    """A second, unrelated draft in the same session must not carry the
    first draft's muhatap/yazan_taraf answers -- see the "taslak oluşturma
    state'inin sıfırlanmaması" bug this guards against."""
    focus = SessionFocus(writing_brief={"muhatap": "Rektörlük", "yazan_taraf": "KACMAK ekibi"})

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Ahmet Yılmaz'a bir izin yazısı hazırla.",
        draft_result={},
        brief_answers={},
    )

    assert update["writing_brief"] == {}


def test_a_new_brief_answer_replaces_the_prior_one():
    focus = SessionFocus(writing_brief={"muhatap": "Rektörlük"})

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Ahmet Yılmaz'a bir izin yazısı hazırla.",
        draft_result={},
        brief_answers={"muhatap": "Ahmet Yılmaz"},
    )

    assert update["writing_brief"] == {"muhatap": "Ahmet Yılmaz"}


def test_no_brief_step_this_turn_leaves_the_existing_writing_brief_untouched():
    focus = SessionFocus(writing_brief={"muhatap": "Rektörlük"})

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="assist",
        input_text="Bu evrakta ne yazıyor?",
        draft_result={},
    )

    assert "writing_brief" not in update


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


def test_a_settled_draft_from_the_revise_step_is_recorded_as_a_revise():
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="revise",
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
    assert version.supersedes == 1
    assert update["draft_history"] == (first, version)


def test_a_second_unrelated_draft_request_is_not_mislabeled_as_a_revise():
    """The version's created_from is keyed off which step produced it, not
    inferred from "a draft already existed" -- a fresh, unrelated draft
    request in a later turn is still a "draft", not a "revise" of the first."""
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Şimdi de başka bir konuda taslak hazırla.",
        draft_result={
            "status": "COMPLETED",
            "draft": "v2",
            "correspondence_type": "cover_letter",
            "combined_score": 90.0,
        },
    )

    assert update["active_draft"].created_from == "draft"
    assert update["active_draft"].supersedes == 0


def test_the_draft_version_carries_its_grounding_forward():
    update = compute_focus_update(
        SessionFocus(),
        document_id=None,
        plan_intent="draft",
        input_text="Cevap yazısı hazırla.",
        draft_result={
            "status": "COMPLETED",
            "draft": "...",
            "correspondence_type": "cover_letter",
            "combined_score": 80.0,
            "classification": {"document_type": "official_letter"},
            "context": "[MEVZUAT] ...",
            "source_document": "Sayı: E-1, ...",
        },
    )

    version = update["active_draft"]
    assert version.classification == {"document_type": "official_letter"}
    assert version.context == "[MEVZUAT] ..."
    assert version.source_document == "Sayı: E-1, ..."


def test_a_failed_or_in_progress_draft_does_not_become_a_version():
    focus = SessionFocus()

    for status in ("FAILED", "IN_PROGRESS"):
        update = compute_focus_update(
            focus,
            document_id=None,
            plan_intent="draft",
            input_text="x",
            draft_result={"status": status, "draft": "..."},
        )
        assert "active_draft" not in update, status


def test_a_revise_requested_draft_is_still_versioned():
    """Unintuitive but correct: REVISE_REQUESTED only ever reaches here as a
    turn's *final* status when the human approval gate's revision-round cap
    was hit (see focus.py's own docstring on _VERSIONABLE_DRAFT_STATUSES) --
    by then draft_result["draft"] is real text from the last completed
    gate_revise round, not a request with nothing behind it."""
    focus = SessionFocus()

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="revise",
        input_text="Bir kez daha revize et.",
        draft_result={
            "status": "REVISE_REQUESTED",
            "draft": "son revize edilmiş metin",
            "correspondence_type": "cover_letter",
            "combined_score": 75.0,
            "instruction_origin": "human_gate",
        },
    )

    version = update["active_draft"]
    assert version.text == "son revize edilmiş metin"
    assert version.created_from == "gate_revise"
    assert update["draft_history"] == (version,)


def test_a_rejected_draft_with_no_new_text_is_annotated_in_place_and_stays_active():
    """Defensive fallback path: no `draft_result["draft"]` at all (not
    reachable through the router today, see the no-op test below for the
    even-more-defensive case) -- the existing active_draft is annotated in
    place rather than manufacturing a duplicate entry with no text."""
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="revise",
        input_text="Bu olmadı, reddediyorum.",
        draft_result={"status": "REJECTED", "rejection_reason": "Üslup çok resmi değil."},
    )

    assert len(update["draft_history"]) == 1
    archived = update["draft_history"][0]
    assert archived.version == 1
    assert archived.text == "v1"
    assert archived.created_from == "rejected"
    assert archived.rejection_reason == "Üslup çok resmi değil."
    # The rejected draft stays active -- a reject is a verdict on the text,
    # not an instruction to forget it (see focus.py's own docstring on
    # _ARCHIVE_ONLY_DRAFT_STATUSES).
    assert update["active_draft"] is archived
    assert update["last_rejection"] == {
        "version": 1, "reason": "Üslup çok resmi değil.", "draft": "v1",
    }


def test_a_rejection_with_no_prior_active_draft_still_archives_the_real_text():
    """The ordinary case, not an edge case: a draft created and rejected
    within the same turn never became `focus.active_draft` first -- the
    gate interrupts before `focus_node` ever runs (see its own docstring).
    `draft_result["draft"]` still carries the real text and must not be
    dropped just because there was no prior version to annotate."""
    focus = SessionFocus()

    update = compute_focus_update(
        focus, document_id=None, plan_intent="draft", input_text="x",
        draft_result={
            "status": "REJECTED", "rejection_reason": "Üslup uygun değil.",
            "draft": "reddedilen ilk taslak",
        },
    )

    archived = update["draft_history"][0]
    assert archived.version == 1
    assert archived.text == "reddedilen ilk taslak"
    assert archived.created_from == "rejected"
    assert archived.rejection_reason == "Üslup uygun değil."
    assert archived.supersedes == 0
    assert update["active_draft"] is archived
    assert update["last_rejection"]["draft"] == "reddedilen ilk taslak"


def test_rejecting_a_revision_keeps_its_own_text_not_the_prior_versions():
    """The bug this fixes: a revision that fixed the content but not the
    tone, then rejected for its tone, must not silently discard the content
    fix by re-archiving the *prior* turn's version instead of this turn's
    real, revised text."""
    first = DraftVersion(
        version=1, text="v1 - eski içerik", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="revise",
        input_text="Üslubu daha resmi yap.",
        draft_result={
            "status": "REJECTED",
            "rejection_reason": "Üslup hâlâ çok resmi değil.",
            "draft": "v2 - düzeltilmiş içerik, yanlış üslup",
            "correspondence_type": "cover_letter",
        },
    )

    assert len(update["draft_history"]) == 2
    # v1 is untouched in history -- it was never the thing rejected.
    assert update["draft_history"][0] is first
    rejected = update["draft_history"][1]
    assert rejected.version == 2
    assert rejected.text == "v2 - düzeltilmiş içerik, yanlış üslup"
    assert rejected.created_from == "rejected"
    assert rejected.supersedes == 1
    assert update["active_draft"] is rejected


def test_rejecting_an_unrelated_fresh_draft_does_not_claim_to_supersede_the_open_one():
    """An unrelated draft request arriving while some other draft is still
    open, then rejected, must not claim to supersede the unrelated open
    draft -- `supersedes` only tracks real revision chains."""
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="Başka bir konuda taslak hazırla.",
        draft_result={
            "status": "REJECTED",
            "rejection_reason": "Bu değil.",
            "draft": "ilgisiz yeni taslak",
        },
    )

    rejected = update["draft_history"][1]
    assert rejected.supersedes == 0


def test_a_gate_revise_round_rejected_at_the_gate_supersedes_the_prior_version():
    first = DraftVersion(
        version=1, text="v1", correspondence_type="cover_letter",
        confidence_score=70.0, created_from="draft",
    )
    focus = SessionFocus(active_draft=first, draft_history=(first,))

    update = compute_focus_update(
        focus,
        document_id=None,
        plan_intent="draft",
        input_text="ignored for gate-originated revisions",
        draft_result={
            "status": "REJECTED",
            "rejection_reason": "Hâlâ olmadı.",
            "draft": "gate üzerinden revize edilmiş metin",
            "instruction_origin": "human_gate",
        },
    )

    rejected = update["draft_history"][1]
    assert rejected.created_from == "rejected"
    assert rejected.supersedes == 1


def test_a_rejection_with_neither_active_draft_nor_text_is_a_no_op():
    """Not reachable through the router today (reject only fires from the
    approval gate, which requires a draft_result to exist) -- defensive."""
    focus = SessionFocus()

    update = compute_focus_update(
        focus, document_id=None, plan_intent="revise", input_text="x",
        draft_result={"status": "REJECTED", "rejection_reason": "..."},
    )

    assert "active_draft" not in update
    assert "draft_history" not in update
    assert "last_rejection" not in update


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
