"""Unit tests for resolve_correspondence_type's deterministic precedence.

Order matters and is deliberate: an explicit caller-supplied type always wins
(it is an instruction, not a guess); the user's own drafting request is
checked next, matched against direction-aware genre surfaces (see
GENRE_SURFACES) rather than orchestrator boilerplate -- this is the fix for
the bug where every chat-initiated draft resolved to RESPONSE_LETTER because
the boilerplate framing ("... resmî ve kurumsal bir Türkçe yanıt taslağı
oluştur.") contains the word "yanıt"; classification metadata is checked
next; only then, and only when an inbound document actually exists, is the
incoming document's own type used to infer the safest output type; and when
nothing matches, the system falls back to "other_official" -- a fallback
result requires human review (see draft_graph.verify_node's
correspondence_type_source == "fallback" check).
"""

import pytest

from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    match_genre,
    resolve_correspondence_type,
)
from app.core.enums.correspondence_type import CorrespondenceType


def test_explicit_request_wins_over_every_other_signal():
    resolved, source, sub_genre = resolve_correspondence_type(
        CorrespondenceType.RESPONSE_LETTER,
        "bir üst yazı hazırla",
        {"metadata": {"correspondence_type": "bilgilendirme"}},
    )
    assert resolved == CorrespondenceType.RESPONSE_LETTER
    assert source == "explicit"
    assert sub_genre == ""


def test_an_unrecognized_explicit_request_falls_back_rather_than_erroring():
    resolved, source, sub_genre = resolve_correspondence_type("not a real type", "", {})
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "fallback"
    assert sub_genre == ""


def test_explicit_request_accepts_a_plain_string_alias():
    resolved, source, _ = resolve_correspondence_type("ust yazi", "", {})
    assert resolved == CorrespondenceType.COVER_LETTER
    assert source == "explicit"


def test_the_orchestrators_own_boilerplate_never_resolves_a_type():
    """Regression lock: the chat orchestrator's fixed framing sentence must
    never itself be mistaken for the user's request. It contains "yanıt",
    which used to match RESPONSE_LETTER's alias set when it was the only
    text resolve_correspondence_type ever saw."""
    boilerplate = (
        "Gelen evraka, evrakın amacı ve doğrulanmış bağlam doğrultusunda "
        "resmî ve kurumsal bir Türkçe yanıt taslağı oluştur."
    )
    resolved, source, _ = resolve_correspondence_type(None, boilerplate, {})
    assert source == "fallback"
    assert resolved == CorrespondenceType.OTHER_OFFICIAL


@pytest.mark.parametrize(
    ("user_request", "expected_type"),
    [
        ("itiraz dilekçesi yaz", CorrespondenceType.OTHER_OFFICIAL),
        ("üst yazı hazırla", CorrespondenceType.COVER_LETTER),
        ("bilgilendirme metni yaz", CorrespondenceType.INFORMATION_NOTICE),
        ("cevap yazısı hazırlar mısın", CorrespondenceType.RESPONSE_LETTER),
    ],
)
def test_user_request_resolves_the_type_the_user_actually_asked_for(
    user_request, expected_type
):
    resolved, source, _ = resolve_correspondence_type(None, user_request, {})
    assert resolved == expected_type
    assert source == "user_request"


def test_a_specific_genre_outside_the_four_types_carries_a_sub_genre_label():
    resolved, source, sub_genre = resolve_correspondence_type(
        None, "itiraz dilekçesi yaz", {}
    )
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "user_request"
    assert sub_genre == "itiraz dilekçesi"


@pytest.mark.parametrize(
    "user_request",
    [
        "dilekçeye cevap yaz",
        "dilekçeyi yanıtla",
        "itiraza cevap hazırla",
        "başvuruya cevap ver",
    ],
)
def test_replying_to_an_inbound_petition_is_a_response_letter_not_a_petition(
    user_request,
):
    """"Dilekçeye cevap yaz" means *reply to* a petition -- the opposite
    direction from "dilekçe yaz" (author one). The longer, more specific
    counter-direction surface must win over the bare "dilekçe" it contains."""
    resolved, source, sub_genre = resolve_correspondence_type(None, user_request, {})
    assert resolved == CorrespondenceType.RESPONSE_LETTER
    assert source == "user_request"
    assert sub_genre == ""


def test_classification_metadata_wins_over_document_type_when_no_genre_in_request():
    resolved, source, _ = resolve_correspondence_type(
        None,
        "uygun bir metin hazırla",
        {"metadata": {"correspondence_type": "üst yazı"}, "doc_type": "Dilekçe"},
        has_source_document=True,
    )
    assert resolved == CorrespondenceType.COVER_LETTER
    assert source == "classification"


@pytest.mark.parametrize(
    ("document_type", "expected"),
    [
        ("Dilekçe", CorrespondenceType.RESPONSE_LETTER),
        ("Şikayet", CorrespondenceType.RESPONSE_LETTER),
        ("Duyuru", CorrespondenceType.INFORMATION_NOTICE),
    ],
)
def test_document_type_is_the_last_resort_inference_when_a_document_exists(
    document_type, expected
):
    resolved, source, _ = resolve_correspondence_type(
        None,
        "Uygun resmî metni hazırla",
        {"doc_type": document_type},
        has_source_document=True,
    )
    assert resolved == expected
    assert source == "document_type"


def test_document_type_inference_never_fires_without_an_actual_inbound_document():
    """The chat-only flow classifies the user's own message; "dilekçe"
    showing up there means "write me a petition", not "reply to one". Without
    this gate the request direction gets silently reversed."""
    resolved, source, _ = resolve_correspondence_type(
        None,
        "uygun bir metin hazırla",
        {"doc_type": "Dilekçe"},
        has_source_document=False,
    )
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "fallback"


def test_nothing_matching_anywhere_falls_back_to_other_official():
    resolved, source, _ = resolve_correspondence_type(
        None, "bir şeyler yaz", {"doc_type": "Bilinmeyen"}, has_source_document=True
    )
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "fallback"


def test_already_resolved_correspondence_type_object_passes_through_as_explicit():
    resolved, source, _ = resolve_correspondence_type(CorrespondenceType.OTHER_OFFICIAL, "", {})
    assert resolved == CorrespondenceType.OTHER_OFFICIAL
    assert source == "explicit"


def test_match_genre_returns_none_for_unrelated_text():
    assert match_genre("bugün hava çok güzel") is None


def test_format_correspondence_profile_includes_the_sub_genre_line_when_set():
    profile = format_correspondence_profile("other_official", "itiraz dilekçesi")
    assert "itiraz dilekçesi" in profile
    assert "Özel Tür" in profile


def test_format_correspondence_profile_omits_the_sub_genre_line_when_unset():
    profile = format_correspondence_profile("response_letter", "")
    assert "Özel Tür" not in profile
