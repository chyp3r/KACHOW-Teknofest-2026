"""Guards content_words -- the "does this instruction carry topic content
beyond its own drafting/revision command" building block shared by
app.ai.workflows.scope and app.ai.workflows.relevance.

The regression this pins: a single-word surface ("hazirla", pulled in from
intent_rules.CONTINUATION_SURFACES) getting stripped before a longer
multi-word command surface ("yazi hazirla") got its turn fragmented the
phrase and left "yazi" behind as if it were topic content -- which made
"Yazı hazırla." (the router's own worked example of an unambiguous draft
request) look suspicious to the scope gate.
"""

from app.ai.workflows.topic_words import content_words


def test_a_bare_multiword_command_leaves_no_content_words():
    assert content_words("Yazı hazırla.") == set()
    assert content_words("Cevap yaz.") == set()
    assert content_words("Kaleme al.") == set()
    assert content_words("Tanzim et.") == set()


def test_a_short_affirmative_continuation_leaves_no_content_words():
    """"evet, hazırla" only ever refers to whatever the previous turn
    already established -- it carries no topic of its own."""
    assert content_words("evet, hazırla") == set()
    assert content_words("Tamam, devam et.") == set()


def test_an_off_topic_noun_phrase_survives_the_strip():
    words = content_words("Çiğköfte kampanyası için bir metin yaz")
    assert "cigkofte" in words
    assert "kampanyasi" in words


def test_a_named_subject_survives_the_strip():
    words = content_words("TOGA projesiyle ilgili bir yazı hazırla")
    assert "toga" in words
    assert "projesiyle" in words
