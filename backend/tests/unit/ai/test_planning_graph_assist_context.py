"""Tests for `planning_graph._assist_document_context`.

The "## Bu Turda Yüklenmiş Belge" block rendered into the assistant's system
prompt. Its one subtle job: when the user swaps the attached document
mid-chat, warn the model that the conversation history / memory summary
still describe a *different* document -- without this the model kept
answering about the old document from that stale memory.
"""

from app.ai.workflows.planning_graph import (
    _DOCUMENT_SWITCHED_NOTE,
    _assist_document_context,
)


def test_no_document_attached():
    text = _assist_document_context(None, document_id=None, prior_document_id=None)
    assert text == "(Bu turda yüklenmiş bir belge yok.)"
    assert _DOCUMENT_SWITCHED_NOTE not in text


def test_first_document_of_the_session_has_no_switch_note():
    text = _assist_document_context(
        "Yıllık izin talebi.", document_id="uploads/a.pdf", prior_document_id=None
    )
    assert "Özet: Yıllık izin talebi." in text
    assert _DOCUMENT_SWITCHED_NOTE not in text


def test_the_summary_is_marked_as_not_being_an_answer_source():
    """The model used to answer document questions straight from this summary
    without searching -- the block has to say, in the prompt itself, that the
    summary is context and not a source."""
    text = _assist_document_context(
        "Yıllık izin talebi.", document_id="uploads/a.pdf", prior_document_id=None
    )
    assert "CEVAP KAYNAĞI DEĞİLDİR" in text


def test_same_document_across_turns_has_no_switch_note():
    text = _assist_document_context(
        "Yıllık izin talebi.",
        document_id="uploads/a.pdf",
        prior_document_id="uploads/a.pdf",
    )
    assert _DOCUMENT_SWITCHED_NOTE not in text


def test_switching_the_document_mid_chat_prepends_the_warning():
    text = _assist_document_context(
        "Disiplin soruşturması raporu.",
        document_id="uploads/b.pdf",
        prior_document_id="uploads/a.pdf",
    )
    assert text.startswith(_DOCUMENT_SWITCHED_NOTE)
    # The current document's own summary still follows the warning.
    assert "Özet: Disiplin soruşturması raporu." in text


def test_missing_summary_still_renders():
    text = _assist_document_context(
        None, document_id="uploads/b.pdf", prior_document_id="uploads/a.pdf"
    )
    assert _DOCUMENT_SWITCHED_NOTE in text
    assert "Özet mevcut değil." in text
