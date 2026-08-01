"""Unit tests for resolve_correspondence_type's 5-tier deterministic precedence.

Order matters and is deliberate: an explicit caller-supplied type always wins
(it is an instruction, not a guess); a type already resolved during
classification is the next most trustworthy signal; the user's own words are
checked next; only then is the incoming document's own type used to infer the
safest output type; and when nothing matches, the system falls back to
"other_official" -- a fallback result requires human review (see
draft_graph.verify_node's correspondence_type_source == "fallback" check).
"""

import pytest

from app.ai.workflows.correspondence import resolve_correspondence_type
from app.core.enums.correspondence_type import CorrespondenceType


def test_explicit_request_wins_over_every_other_signal():
    resolved, source = resolve_correspondence_type(
        CorrespondenceType.RESPONSE_LETTER,
        "bir üst yazı hazırla",
        {"metadata": {"correspondence_type": "bilgilendirme"}},
    )
    assert resolved == CorrespondenceType.RESPONSE_LETTER
    assert source == "explicit"


def test_an_unrecognized_explicit_request_falls_back_rather_than_erroring():
    resolved, source = resolve_correspondence_type("not a real type", "", {})
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "fallback"


def test_explicit_request_accepts_a_plain_string_alias():
    resolved, source = resolve_correspondence_type("ust yazi", "", {})
    assert resolved == CorrespondenceType.COVER_LETTER
    assert source == "explicit"


def test_classification_metadata_wins_over_instructions_and_document_type():
    resolved, source = resolve_correspondence_type(
        None,
        "bilgilendirme metni hazırla",
        {"metadata": {"correspondence_type": "üst yazı"}, "doc_type": "Dilekçe"},
    )
    assert resolved == CorrespondenceType.COVER_LETTER
    assert source == "classification"


def test_instructions_win_over_document_type_when_classification_is_silent():
    resolved, source = resolve_correspondence_type(
        None, "Bilgilendirme metni hazırla", {"doc_type": "Dilekçe"}
    )
    assert resolved == CorrespondenceType.INFORMATION_NOTICE
    assert source == "instructions"


@pytest.mark.parametrize(
    ("document_type", "expected"),
    [
        ("Dilekçe", CorrespondenceType.RESPONSE_LETTER),
        ("Şikayet", CorrespondenceType.RESPONSE_LETTER),
        ("Duyuru", CorrespondenceType.INFORMATION_NOTICE),
    ],
)
def test_document_type_is_the_last_resort_inference(document_type, expected):
    resolved, source = resolve_correspondence_type(
        None, "Uygun resmî metni hazırla", {"doc_type": document_type}
    )
    assert resolved == expected
    assert source == "document_type"


def test_nothing_matching_anywhere_falls_back_to_other_official():
    resolved, source = resolve_correspondence_type(None, "bir şeyler yaz", {"doc_type": "Bilinmeyen"})
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "fallback"


def test_already_resolved_correspondence_type_object_passes_through_as_explicit():
    resolved, source = resolve_correspondence_type(CorrespondenceType.OTHER_OFFICIAL, "", {})
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "explicit"
