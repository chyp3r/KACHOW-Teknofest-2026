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


def _question(resolution, key):
    return next(question for question in resolution.questions if question["key"] == key)


def _option(question, value):
    return next(option for option in question["options"] if option["value"] == value)


def test_a_weak_name_signal_is_suggested_not_silently_resolved():
    resolution = resolve_brief("Ahmet Yılmaz olarak izin talep ediyorum.")

    # Not confident enough to skip the question outright...
    assert "yazan_taraf" not in resolution.resolved
    # ...but the guess rides along as the question's own suggested option.
    question = _question(resolution, "yazan_taraf")
    option = _option(question, "Ahmet Yılmaz")
    assert "Önerilen" in option["label"]
    # And "Sen karar ver" is still offered alongside it -- a slot with no
    # catalog options of its own must never lose the auto option either.
    assert any(option["value"] == AUTO_ANSWER for option in question["options"])


def test_a_dative_marked_proper_noun_suggests_the_addressee():
    # Not in the curated institution vocabulary -- otherwise this would
    # resolve confidently via that lookup instead of exercising the weak
    # dative-suffix pattern this test targets. Lowercase sentence start on
    # purpose: a leading capital would itself match the name-token pattern
    # and get swept into the match, which is a known sharp edge of a
    # "suggestion, not authoritative" heuristic -- see the module docstring.
    resolution = resolve_brief("başvurumuzu Fen Fakültesi'ne iletmek istiyoruz.")

    assert "muhatap" not in resolution.resolved
    question = _question(resolution, "muhatap")
    option = _option(question, "Fen Fakültesi")
    assert "Önerilen" in option["label"]


def test_kapanis_suggests_arz_from_an_authority_muhatap_without_an_explicit_word():
    resolution = resolve_brief("Rektörlük onayına ihtiyacımız var, bir yazı hazırla.")

    # muhatap resolved confidently from the curated vocabulary...
    assert resolution.resolved["muhatap"].value == "Rektörlük"
    # ...and kapanis, seeing no explicit "arz"/"rica", still asks -- but
    # recommends "Arz ederim" instead of listing all four options flatly.
    assert "kapanis" not in resolution.resolved
    question = _question(resolution, "kapanis")
    assert "Önerilen" in question["options"][0]["label"]
    assert question["options"][0]["value"] == "arz_ederim"
    # The recommended option replaces, not duplicates, the catalog's own
    # "arz_ederim" entry.
    assert sum(1 for option in question["options"] if option["value"] == "arz_ederim") == 1


def test_a_genuinely_unknown_slot_has_no_option_marked_as_a_suggestion():
    resolution = resolve_brief("bir yazı hazırla")
    question = _question(resolution, "kapanis")
    assert not any("Önerilen" in option["label"] for option in question["options"])
