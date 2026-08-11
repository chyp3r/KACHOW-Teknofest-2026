"""Unit tests for the pre-draft writing-brief resolver.

The headline case is the motivating bug: "...dilekçe yazmak istiyoruz KACMAK
ekibi olarak" must resolve who's writing without asking, and never
misplaces that name as the addressee.
"""

from app.ai.workflows.writing_brief import (
    AUTO_ANSWER,
    MAX_BRIEF_QUESTIONS,
    resolve_brief,
)


def test_resolves_the_writing_team_from_a_collective_noun_without_asking():
    resolution = resolve_brief(
        "yarışmaya katılım için neler gerekiyor öğrenmek için dilekçe yazmak "
        "istiyoruz KACMAK ekibi olarak"
    )

    assert resolution.resolved["yazan_taraf"].value == "KACMAK ekibi"
    assert resolution.resolved["yazan_taraf"].source == "user_text"
    assert resolution.resolved["anlatim"].value == "birinci_cogul"
    assert "muhatap" not in resolution.resolved
    assert any(question["key"] == "muhatap" for question in resolution.questions)


def test_preserves_original_casing_and_diacritics_in_the_extracted_name():
    resolution = resolve_brief("Hacettepe Bilişim Kulübü olarak başvuru yapmak istiyoruz.")
    assert resolution.resolved["yazan_taraf"].value == "Hacettepe Bilişim Kulübü"


def test_document_reply_inverts_sender_and_addressee():
    classification = {"fields": {"gonderen_kurum": "TEKNOFEST Bilişim Vadisi", "muhatap": None}}
    resolution = resolve_brief("Bu evraka cevap yazısı hazırla", classification)

    assert resolution.resolved["muhatap"].value == "TEKNOFEST Bilişim Vadisi"
    assert resolution.resolved["muhatap"].source == "document_reply"


def test_a_fully_determined_turn_asks_nothing():
    classification = {
        "fields": {"gonderen_kurum": "TEKNOFEST Bilişim Vadisi", "muhatap": "KACMAK Ekibi"}
    }
    resolution = resolve_brief(
        "KACMAK ekibi olarak arz ederim şeklinde bir cevap yazısı hazırla",
        classification,
    )

    assert resolution.questions == ()


def test_prior_brief_answers_are_carried_forward_without_asking_again():
    prior = {"muhatap": "TEKNOFEST Yarışma Komitesi", "kapanis": AUTO_ANSWER}
    resolution = resolve_brief("dilekçe yazmak istiyoruz KACMAK ekibi olarak", None, prior)

    assert resolution.resolved["muhatap"].value == "TEKNOFEST Yarışma Komitesi"
    assert resolution.resolved["muhatap"].source == "prior_brief"
    assert resolution.resolved["kapanis"].value == AUTO_ANSWER
    assert not any(question["key"] in {"muhatap", "kapanis"} for question in resolution.questions)


def test_question_count_never_exceeds_the_cap():
    resolution = resolve_brief("bir dilekçe yaz")
    assert len(resolution.questions) <= MAX_BRIEF_QUESTIONS


def test_resolution_is_idempotent_for_the_frontend_dedup_hash():
    text = "yarışmaya katılım için dilekçe yazmak istiyoruz KACMAK ekibi olarak"
    first = resolve_brief(text)
    second = resolve_brief(text)

    first_keys = [question["key"] for question in first.questions]
    second_keys = [question["key"] for question in second.questions]
    assert first_keys == second_keys


def test_explicit_arz_and_rica_resolves_the_combined_closing():
    resolution = resolve_brief("arz ve rica ederim şeklinde bir yazı hazırla")
    assert resolution.resolved["kapanis"].value == "arz_ve_rica_ederim"


def test_bare_dilekce_without_a_collective_noun_infers_first_person_singular():
    resolution = resolve_brief("izin almak için bir dilekçe yazmak istiyorum")
    assert resolution.resolved["anlatim"].value == "birinci_tekil"
