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


# ==========================================
# Muhatap extraction (Görev's "metinden alıcı bilgisinin çıkarılamaması" bug)
# ==========================================
def test_a_single_named_addressee_with_a_drafting_verb_resolves_confidently():
    """The bug this closes: "Ahmet Yılmaz'a bir yazı hazırla" used to still
    ask "Yazı kime gönderilecek?" despite the recipient being named
    outright -- a single candidate said in the same breath as an actual
    drafting request should never need confirming."""
    resolution = resolve_brief("Ahmet Yılmaz'a bir izin yazısı hazırla")

    assert resolution.resolved["muhatap"].value == "Ahmet Yılmaz"
    assert resolution.resolved["muhatap"].source == "user_text"
    assert not any(question["key"] == "muhatap" for question in resolution.questions)


def test_the_same_addressee_without_the_apostrophe_still_resolves_confidently():
    resolution = resolve_brief("Ahmet Yılmaza bir izin yazısı hazırla")
    assert resolution.resolved["muhatap"].value == "Ahmet Yılmaz"


def test_a_multi_word_institution_in_the_bare_dative_form_resolves_confidently():
    resolution = resolve_brief("İnsan Kaynakları Müdürlüğüne bir bilgilendirme yazısı hazırla")
    assert resolution.resolved["muhatap"].value == "İnsan Kaynakları Müdürlüğü"


def test_a_sayin_salutation_resolves_confidently_with_a_drafting_verb():
    resolution = resolve_brief("Sayın Ahmet Yılmaz için bir yazı hazırla")
    assert resolution.resolved["muhatap"].value == "Ahmet Yılmaz"


def test_a_bey_honorific_resolves_confidently_with_a_drafting_verb():
    resolution = resolve_brief("Ahmet Bey'e bir davet yazısı oluştur")
    assert resolution.resolved["muhatap"].value == "Ahmet Bey"


def test_a_named_addressee_with_no_drafting_verb_is_only_a_suggestion():
    """Naming someone isn't itself a request -- without a verb corroborating
    it, the guess still needs confirming."""
    resolution = resolve_brief("Ahmet Yılmaz'a bu konuyu ilettim.")

    assert "muhatap" not in resolution.resolved
    question = _question(resolution, "muhatap")
    option = _option(question, "Ahmet Yılmaz")
    assert "Önerilen" in option["label"]


def test_two_named_candidates_stay_a_suggestion_even_with_a_drafting_verb():
    """More than one plausible addressee is exactly the ambiguity a
    confirmation question exists for."""
    resolution = resolve_brief("Ahmet Yılmaz'a ve Ayşe Kaya'ya bir yazı hazırla")

    assert "muhatap" not in resolution.resolved
    question = _question(resolution, "muhatap")
    assert question["key"] == "muhatap"


def test_a_suggested_muhatap_question_is_phrased_as_a_yes_no_confirmation():
    resolution = resolve_brief("Ahmet Yılmaz'a bu konuyu ilettim.")
    question = _question(resolution, "muhatap")
    assert question["question"] == "Önerilen muhatap: Ahmet Yılmaz. Bu doğru mu?"


def test_a_genuinely_unknown_slot_has_no_option_marked_as_a_suggestion():
    # "cevap yazısı hazırla" resolves `yazisma_turu` confidently (see
    # test_writing_brief_yazisma_turu.py's crowding-out test for the
    # opposite case), so it doesn't compete for one of MAX_BRIEF_QUESTIONS --
    # leaving room for yazan_taraf/muhatap/anlatim/kapanis, all four
    # genuinely unknown here, to all be asked.
    resolution = resolve_brief("cevap yazısı hazırla")
    question = _question(resolution, "kapanis")
    assert not any("Önerilen" in option["label"] for option in question["options"])
