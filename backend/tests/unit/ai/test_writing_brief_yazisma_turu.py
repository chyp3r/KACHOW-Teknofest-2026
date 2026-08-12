"""Unit tests for the writing-brief gate's ``yazisma_turu`` slot.

Priority 0 (see ``SLOT_CATALOG``): when the user's request doesn't already
name a correspondence type, this is the first thing asked, ahead of
yazan_taraf/muhatap/anlatim/kapanis -- getting the type wrong reshapes the
whole draft, unlike those, which a cheap revise turn can fix afterwards.
"""

from app.ai.workflows.writing_brief import AUTO_ANSWER, resolve_brief


def _question(resolution, key):
    return next(question for question in resolution.questions if question["key"] == key)


def test_a_recognized_genre_in_the_request_resolves_without_asking():
    resolution = resolve_brief("itiraz dilekçesi yaz")
    resolved = resolution.resolved["yazisma_turu"]
    assert resolved.value == "other_official"
    assert resolved.source == "user_text"
    assert not any(question["key"] == "yazisma_turu" for question in resolution.questions)


def test_an_unresolved_type_is_asked_first_and_offers_all_four_options():
    resolution = resolve_brief("bir yazı hazırla")
    question = _question(resolution, "yazisma_turu")
    values = {option["value"] for option in question["options"]}
    assert {
        "cover_letter",
        "response_letter",
        "information_notice",
        "other_official",
        AUTO_ANSWER,
    } <= values


def test_an_unresolved_type_can_crowd_out_a_lower_priority_slot():
    """MAX_BRIEF_QUESTIONS caps the round at 4. With yazisma_turu also
    unresolved (priority 0) alongside all four other required slots, the
    lowest-priority one (kapanis, priority 4) is the one left out this
    round -- not silently dropped forever, just not asked yet."""
    resolution = resolve_brief("bir yazı hazırla")
    keys = [question["key"] for question in resolution.questions]
    assert len(keys) <= 4
    assert "yazisma_turu" in keys
    assert "kapanis" not in keys


def test_prior_brief_carries_the_type_forward_without_re_asking():
    prior = {"yazisma_turu": "response_letter"}
    resolution = resolve_brief("bir yazı hazırla", None, prior)
    assert resolution.resolved["yazisma_turu"].value == "response_letter"
    assert resolution.resolved["yazisma_turu"].source == "prior_brief"
    assert not any(question["key"] == "yazisma_turu" for question in resolution.questions)
