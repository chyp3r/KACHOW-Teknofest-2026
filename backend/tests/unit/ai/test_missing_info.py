"""Unit tests for the deterministic missing-information request builder.

Deterministic and LLM-free by design: this is the HITL trigger for Görev 2's
"eksik bilgi talep edebilmesi" requirement, and it must produce the same
questions for the same draft every time, including on the resume path where
nothing regenerates the draft.
"""

from app.ai.verification.draft_verifier import VerificationReport
from app.ai.verification.missing_info import (
    InfoQuestion,
    apply_answers,
    build_missing_info_request,
    resolve_placeholders_from_brief,
)
from app.ai.workflows.writing_brief import AUTO_ANSWER

REPORT = VerificationReport(confidence_score=40.0, requires_human_approval=True, placeholder_count=1)


def test_each_distinct_placeholder_becomes_one_question():
    draft = "Sayın [MUHATAP],\n\n[KONU] hakkında bilgi arz ederim.\n\n[İMZA SAHİBİ]"
    questions = build_missing_info_request(draft, REPORT)

    assert [q.key for q in questions] == ["muhatap", "konu", "imza_sahibi"]
    assert [q.label for q in questions] == ["MUHATAP", "KONU", "İMZA SAHİBİ"]


def test_repeated_placeholder_text_deduplicates_to_one_question():
    draft = "[MUHATAP] için hazırlanan bu yazı [MUHATAP] onayına sunulmuştur."
    questions = build_missing_info_request(draft, REPORT)

    assert len(questions) == 1


def test_draft_without_placeholders_yields_no_questions():
    assert build_missing_info_request("Tamamen dolu bir taslak metni.", REPORT) == []


def test_matches_compliance_missing_field_for_its_legal_justification():
    draft = "Sayın [MUHATAP],"
    classification = {
        "missing_fields": [
            {
                "key": "muhatap",
                "label": "Muhatap",
                "mevzuat": "RYUEHY m.14",
                "reason": "Muhatap belirtilmelidir.",
            }
        ]
    }
    questions = build_missing_info_request(draft, REPORT, classification)

    assert questions[0].why == "RYUEHY m.14 -- Muhatap belirtilmelidir."


def test_unmatched_placeholder_still_gets_a_generic_help_string():
    """Bir compliance kuralına eşleşmeyen bir yer tutucu bile bağlamsız
    kalmamalı: ``why`` daima dolu (genel açıklama), ``example`` ise bilinen
    bir alan şekli değilse ``None``."""
    draft = "[RASTGELE BİLGİ] eksik."
    questions = build_missing_info_request(draft, REPORT, {"missing_fields": []})

    assert questions[0].why != ""
    assert "RASTGELE BİLGİ" in questions[0].why
    assert questions[0].example is None


def test_apply_answers_substitutes_and_reports_no_residual_when_complete():
    draft = "Sayın [MUHATAP], [KONU] hakkında arz ederim."
    substituted, residual = apply_answers(
        draft, {"muhatap": "İlgili Makama", "konu": "İzin Talebi"}
    )

    assert substituted == "Sayın İlgili Makama, İzin Talebi hakkında arz ederim."
    assert residual == []


def test_apply_answers_leaves_unanswered_placeholders_intact_and_reports_them():
    draft = "Sayın [MUHATAP], [KONU] hakkında arz ederim."
    substituted, residual = apply_answers(draft, {"muhatap": "İlgili Makama"})

    assert "[KONU]" in substituted
    assert "İlgili Makama" in substituted
    assert residual == ["konu"]


def test_apply_answers_round_trips_with_build_missing_info_request_keys():
    """The keys build_missing_info_request hands to the client must be exactly
    the keys apply_answers expects back on resume."""
    draft = "Sayın [MUHATAP], [KONU] hakkında arz ederim."
    questions = build_missing_info_request(draft, REPORT)
    answers = {q.key: f"cevap-{q.key}" for q in questions}

    substituted, residual = apply_answers(draft, answers)

    assert residual == []
    assert "[" not in substituted


def test_apply_answers_ignores_blank_or_whitespace_only_answers():
    draft = "Sayın [MUHATAP] arz ederim."
    substituted, residual = apply_answers(draft, {"muhatap": "   "})

    assert "[MUHATAP]" in substituted
    assert residual == ["muhatap"]


def test_the_responses_own_tarih_header_line_is_never_asked_about():
    """C7 regression: the exact `Tarih: [...]` header line -- the one
    `fill_date_placeholders` is responsible for -- must still be skipped."""
    draft = "Sayı: [Belge Sayısı]\nTarih: [Tarih]\nKonu: Test"
    questions = build_missing_info_request(draft, REPORT)

    assert [q.key for q in questions] == ["belge_sayisi"]


def test_an_unrelated_date_labelled_placeholder_is_still_asked_about():
    """C7 regression: build_missing_info_request used to skip ANY
    placeholder whose folded text merely started with "tarih" -- silently
    swallowing a real information gap like "[Tarihi belirtiniz]" or
    "[Son Başvuru Tarihi]" into never being asked about, while
    apply_answers (with no matching skip) still counted the very same
    placeholder as residual on resume -- a NEEDS_INPUT round with zero
    questions in it and no way to answer it."""
    draft = "Tarih: [Tarih]\n\nSon Başvuru Tarihi: [Tarihi belirtiniz]"
    questions = build_missing_info_request(draft, REPORT)

    assert [q.key for q in questions] == ["tarihi_belirtiniz"]

    # And the two functions must agree: answering every *asked* question
    # leaves nothing this draft's own header line wasn't already exempt
    # from being asked about.
    answers = {q.key: "01.01.2026" for q in questions}
    substituted, residual = apply_answers(draft, answers)
    assert "[Tarihi belirtiniz]" not in substituted
    assert residual == ["tarih"]  # the exempt header line, never asked, never answerable


def test_apply_answers_leaves_an_auto_answer_placeholder_untouched_and_unresidual():
    """"Sen karar ver" (AUTO_ANSWER) must neither leak its own sentinel
    text into the draft nor reopen the gate by counting as unanswered --
    either of those regressions bricked the missing-information gate's
    "acceptAllDefaults" button."""
    draft = "Muhatap: [Alıcının adı ve soyadı]\nİmza: [İmzalayacak yetkilinin adı ve soyadı]"
    substituted, residual = apply_answers(
        draft,
        {
            "alicinin_adi_ve_soyadi": AUTO_ANSWER,
            "imzalayacak_yetkilinin_adi_ve_soyadi": "Ahmet Yılmaz",
        },
    )

    assert AUTO_ANSWER not in substituted
    assert "[Alıcının adı ve soyadı]" in substituted
    assert "Ahmet Yılmaz" in substituted
    assert residual == []


# --- açıklayıcı metin (taslak <-> revizyon tutarlılığı) -----------------------


def test_help_text_is_always_populated_and_names_the_field():
    """Her iki akış da aynı ``human_gate``'i paylaşır; sorulan her alan için
    ``why`` (yardım) daima dolu olmalı."""
    draft = "Sayın [MUHATAP],\n\n[KONU] hakkında.\n\nSayı: [BELGE SAYISI]"
    questions = build_missing_info_request(draft, REPORT, {"missing_fields": []})

    assert all(q.why for q in questions)
    assert all(q.key in q.why or q.label in q.why or len(q.why) > 20 for q in questions)


def test_example_is_populated_for_known_field_shapes():
    draft = "Sayın [MUHATAP],\n\nSayı: [BELGE SAYISI]"
    by_key = {q.key: q for q in build_missing_info_request(draft, REPORT, {"missing_fields": []})}

    assert by_key["muhatap"].example
    assert by_key["belge_sayisi"].example


def test_signer_name_and_title_get_distinct_examples():
    """Writer iki ayrı imza yer tutucusu bırakır; HITL'de ad sorusu ile unvan
    sorusu aynı "Ahmet Yılmaz / Daire Başkanı" önerisini göstermemeli."""
    draft = (
        "Bilgilerinize arz ederim.\n\n"
        "[İmzalayacak yetkilinin adı ve soyadı]\n"
        "[İmzalayacak yetkilinin unvanı]"
    )
    by_key = {q.key: q for q in build_missing_info_request(draft, REPORT, {"missing_fields": []})}

    assert by_key["imzalayacak_yetkilinin_adi_ve_soyadi"].example == "Ahmet Yılmaz"
    assert by_key["imzalayacak_yetkilinin_unvani"].example == "Daire Başkanı"


def test_generic_fallback_help_no_longer_mentions_sen_karar_ver():
    """Eksik-bilgi kartında "Sen karar ver" kontrolü yok; yardım metni de
    kullanıcıyı ona yönlendirmemeli."""
    questions = build_missing_info_request(
        "Metinde bir [Tuhaf Alan] var.", REPORT, {"missing_fields": []}
    )

    assert questions
    assert all("Sen karar ver" not in q.why for q in questions)


def test_compliance_match_still_wins_over_the_generic_help():
    draft = "Sayın [MUHATAP],"
    classification = {
        "missing_fields": [
            {"key": "muhatap", "label": "Muhatap", "mevzuat": "RYUEHY m.14", "reason": "Belirtilmeli."}
        ]
    }
    questions = build_missing_info_request(draft, REPORT, classification)

    assert questions[0].why == "RYUEHY m.14 -- Belirtilmeli."


def test_prompt_question_keeps_key_byte_identical_and_names_the_label():
    payload = InfoQuestion(key="muhatap", label="MUHATAP", why="x").to_prompt_question()

    assert payload["key"] == "muhatap"
    assert "MUHATAP" in payload["question"]


def test_draft_flow_positional_call_signature_is_unchanged():
    """Yeni kwarg'lar opsiyonel: draft_graph'ın 3-pozisyonel çağrısı aynı
    key'leri üretmeye devam eder."""
    draft = "Sayın [MUHATAP],\n\n[KONU] hakkında arz ederim."
    questions = build_missing_info_request(draft, REPORT, {"missing_fields": []})

    assert [q.key for q in questions] == ["muhatap", "konu"]


# --- tekrar-sorma engeli -----------------------------------------------------


def test_resolved_keys_suppress_a_re_ask_for_a_real_answer():
    draft = "Sayın [MUHATAP], [KONU] hakkında."
    questions = build_missing_info_request(
        draft, REPORT, {"missing_fields": []}, resolved_keys={"muhatap": "Yarışma Komitesi"}
    )

    assert [q.key for q in questions] == ["konu"]


def test_resolved_keys_suppress_a_re_ask_for_a_deferred_auto_answer():
    draft = "Sayın [MUHATAP], [KONU] hakkında."
    questions = build_missing_info_request(
        draft, REPORT, {"missing_fields": []}, resolved_keys={"muhatap": AUTO_ANSWER}
    )

    assert [q.key for q in questions] == ["konu"]


def test_known_placeholder_is_resolved_from_writing_brief():
    draft = "Sayın [Muhatap], [KONU] hakkında."
    questions = build_missing_info_request(
        draft, REPORT, {"missing_fields": []}, writing_brief={"muhatap": "X Bakanlığı"}
    )

    assert [q.key for q in questions] == ["konu"]


def test_writing_brief_auto_answer_slot_is_not_treated_as_resolved():
    draft = "Sayın [Muhatap],"
    questions = build_missing_info_request(
        draft, REPORT, {"missing_fields": []}, writing_brief={"muhatap": AUTO_ANSWER}
    )

    assert [q.key for q in questions] == ["muhatap"]


def test_resolve_placeholders_from_brief_maps_aliases():
    draft = "Gönderen kurum: [Gönderen kurumun adı]\nSayın [Alıcının adı ve soyadı],"
    resolved = resolve_placeholders_from_brief(
        draft, {"yazan_taraf": "KACMAK Ekibi", "muhatap": "Yarışma Komitesi"}
    )

    assert resolved.get("gonderen_kurumun_adi") == "KACMAK Ekibi"
    assert resolved.get("alicinin_adi_ve_soyadi") == "Yarışma Komitesi"


def test_resolve_placeholders_from_brief_ignores_auto_answer_and_empty():
    draft = "Sayın [Muhatap],"

    assert resolve_placeholders_from_brief(draft, {"muhatap": AUTO_ANSWER}) == {}
    assert resolve_placeholders_from_brief(draft, {"muhatap": "  "}) == {}
    assert resolve_placeholders_from_brief(draft, None) == {}
