"""Unit tests for the pure, I/O-free preference-pair compiler (Faz C3)."""

from app.ai.training.dataset import (
    FeedbackRecord,
    compile_pairs_from_feedback,
    pair_hash,
)


def _record(**overrides) -> FeedbackRecord:
    fields = dict(feedback_id="fb-1", signal="like", content="Sayın Makam, arz ederim.")
    fields.update(overrides)
    return FeedbackRecord(**fields)


def test_a_like_becomes_a_chosen_only_pair():
    pairs = compile_pairs_from_feedback("company-1", [_record(signal="like")])
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.chosen == "Sayın Makam, arz ederim."
    assert pair.rejected is None


def test_a_dislike_becomes_a_rejected_only_pair():
    pairs = compile_pairs_from_feedback("company-1", [_record(signal="dislike")])
    pair = pairs[0]
    assert pair.rejected == "Sayın Makam, arz ederim."
    assert pair.chosen is None


def test_a_record_with_blank_content_is_skipped():
    pairs = compile_pairs_from_feedback("company-1", [_record(content="   ")])
    assert pairs == []


def test_pair_hash_is_stable_across_recompiles_of_the_same_feedback_row():
    pairs_first = compile_pairs_from_feedback("company-1", [_record(feedback_id="fb-42")])
    pairs_second = compile_pairs_from_feedback("company-1", [_record(feedback_id="fb-42")])
    assert pairs_first[0].pair_hash == pairs_second[0].pair_hash


def test_pair_hash_changes_when_signal_flips_but_identity_stays_stable():
    """A re-vote (like -> dislike) updates the same feedback row in place
    (see FeedbackModel's docstring), so recompiling must upsert onto the
    same training_samples row -- the pair_hash itself must not depend on
    signal/content, only on (company_id, source, feedback_id)."""
    liked = compile_pairs_from_feedback("company-1", [_record(signal="like")])[0]
    disliked = compile_pairs_from_feedback("company-1", [_record(signal="dislike")])[0]
    assert liked.pair_hash == disliked.pair_hash


def test_pair_hash_differs_across_companies_for_the_same_feedback_identity():
    """Defensive: even though feedback ids are already company-scoped in
    practice, the hash itself should not accidentally collide across
    tenants if that ever stopped being true."""
    assert pair_hash("company-1", "explicit_feedback", "fb-1") != pair_hash(
        "company-2", "explicit_feedback", "fb-1"
    )


def test_prompt_context_carries_correspondence_type_and_confidence_score():
    pairs = compile_pairs_from_feedback(
        "company-1",
        [_record(correspondence_type="cover_letter", confidence_score=87.4)],
    )
    assert "cover_letter" in pairs[0].prompt_context
    assert "87" in pairs[0].prompt_context


def test_source_and_draft_id_are_carried_through():
    pairs = compile_pairs_from_feedback("company-1", [_record(draft_id="draft-9")])
    assert pairs[0].source == "explicit_feedback"
    assert pairs[0].source_feedback_id == "fb-1"
    assert pairs[0].source_draft_id == "draft-9"
