"""Unit tests for scripts/generate_yazisma_vaka_pilotu.py's pure logic.

No LLM/Evren/mevzuat-MCP calls here -- those need a live API key and
network, and are exercised manually per VAKA_URETIM_PLAYBOOK.md. This file
only covers the deterministic schema guard and text-safety helpers.
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import generate_yazisma_vaka_pilotu as pilot  # noqa: E402


def test_allowed_decisions_matches_the_plan_document_enum():
    """The 8-value decision enum from GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md.
    ``itiraz`` must never be a member: it is an incoming_type, not a
    decision (see the schema-fix note in TARGET_DECISIONS's docstring)."""
    assert pilot.ALLOWED_DECISIONS == {
        "tam_kabul",
        "ret",
        "kismi_kabul",
        "eksik_belge",
        "yetkisizlik",
        "yalnizca_bilgilendirme",
        "belirsiz_basvuru",
        "coklu_talep",
    }
    assert "itiraz" not in pilot.ALLOWED_DECISIONS


def test_target_decisions_covers_exactly_the_allowed_decisions():
    """Aşama 2/3: the 240-case quota must cover all 8 decision types
    exactly once each -- no missing type, no invalid key (this is exactly
    how ``itiraz`` ended up as a decision value in the first pilot run).
    The module already asserts this at import time; this test documents
    and pins that behaviour."""
    assert pilot.TARGET_DECISIONS.keys() == pilot.ALLOWED_DECISIONS


def test_target_decisions_quota_sums_to_240():
    assert sum(spec["adet"] for spec in pilot.TARGET_DECISIONS.values()) == 240
    assert pilot.TOTAL_TARGET_CASES == 240


def test_case_targets_are_round_robin_for_a_balanced_validation_batch():
    first_sixteen = list(pilot._iter_case_targets())[:16]
    decisions = [decision for decision, _spec, _index in first_sixteen]

    assert set(decisions[:8]) == pilot.ALLOWED_DECISIONS
    assert set(decisions[8:16]) == pilot.ALLOWED_DECISIONS
    assert {decision: decisions.count(decision) for decision in decisions} == {
        decision: 2 for decision in pilot.ALLOWED_DECISIONS
    }


def test_case_targets_preserve_all_240_quotas():
    targets = list(pilot._iter_case_targets())

    assert len(targets) == 240
    for decision, spec in pilot.TARGET_DECISIONS.items():
        assert sum(target_decision == decision for target_decision, _, _ in targets) == spec["adet"]


def test_every_planned_case_id_is_unique_and_targetable():
    case_ids = [
        pilot._case_id(decision, index)
        for decision, _spec, index in pilot._iter_case_targets()
    ]

    assert len(case_ids) == 240
    assert len(set(case_ids)) == 240
    assert "GKC-EKSIK_BELGE-002" in case_ids
    assert "GKC-BELIRSIZ_BASVURU-002" in case_ids


def test_itiraz_quota_meets_minimum_and_overall_share_target():
    """Every decision type must carry at least ITIRAZ_MIN_PER_DECISION
    itiraz cases, and the total itiraz share across all 240 must land in
    the planned 15-20% band."""
    per_decision = {
        decision: pilot._itiraz_count_for(spec["adet"])
        for decision, spec in pilot.TARGET_DECISIONS.items()
    }
    for decision, count in per_decision.items():
        assert count >= pilot.ITIRAZ_MIN_PER_DECISION, decision

    total_itiraz = sum(per_decision.values())
    share = total_itiraz / pilot.TOTAL_TARGET_CASES
    assert pilot.ITIRAZ_MIN_SHARE <= share <= pilot.ITIRAZ_MAX_SHARE, share


def test_each_decision_has_enough_real_few_shot_examples():
    """A quota whose few_shot_glob/niyet_filter can't find at least
    FEW_SHOT_PER_TYPE real candidate cards would silently degrade to
    'atlandı' for every case of that type during the real run -- this
    check catches that before any Evren call is spent."""
    for decision, spec in pilot.TARGET_DECISIONS.items():
        examples = pilot._load_few_shots(
            spec["few_shot_glob"], pilot.FEW_SHOT_PER_TYPE, niyet_filter=spec.get("niyet_filter")
        )
        assert len(examples) >= pilot.FEW_SHOT_PER_TYPE, (
            decision,
            spec["few_shot_glob"],
            spec.get("niyet_filter"),
        )


def test_extract_institution_reads_a_letterhead_line():
    # A gold_draft's own letterhead, not an incoming petition's addressee
    # line -- _extract_institution reads who is SPEAKING, matched against
    # prepare_resmi_yazisma_markdown._INSTITUTION_LINE's known suffixes
    # (BAKANLIĞI/VALİLİĞİ/KAYMAKAMLIĞI/...).
    text = "T.C.\nİZMİR VALİLİĞİ\nİl Sağlık Müdürlüğü\n\nSayı: E-2026/1"
    assert pilot._extract_institution(text) == "İZMİR VALİLİĞİ"


def test_extract_institution_returns_none_without_a_letterhead():
    assert pilot._extract_institution("Sayın Yetkili, başvurumu inceleyiniz.") is None


def test_load_existing_case_ids_reads_case_ids_for_resume(tmp_path):
    path = tmp_path / "vakalar.jsonl"
    path.write_text(
        '{"case_id": "GKC-RET-001", "x": 1}\n{"case_id": "GKC-RET-002", "x": 2}\n',
        encoding="utf-8",
    )
    assert pilot._load_existing_case_ids(path) == {"GKC-RET-001", "GKC-RET-002"}


def test_load_existing_case_ids_is_empty_for_a_missing_file(tmp_path):
    assert pilot._load_existing_case_ids(tmp_path / "yok.jsonl") == set()


def test_institution_counts_restore_previous_batches_for_resume():
    cases = [
        {"provenance": {"kurum_tahmini": "T.C. İzmir Valiliği"}},
        {"provenance": {"kurum_tahmini": "T.C. İzmir Valiliği"}},
        {"provenance": {"kurum_tahmini": "T.C. Ankara Valiliği"}},
        {"provenance": {"kurum_tahmini": None}},
    ]

    assert pilot._institution_counts(cases) == {
        "T.C. İzmir Valiliği": 2,
        "T.C. Ankara Valiliği": 1,
    }


def test_append_jsonl_is_additive_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "vakalar.jsonl"

    pilot._append_jsonl(path, {"case_id": "GKC-RET-001"})
    pilot._append_jsonl(path, {"case_id": "GKC-RET-002"})

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [pilot.json.loads(l)["case_id"] for l in lines] == [
        "GKC-RET-001",
        "GKC-RET-002",
    ]


def test_incoming_type_itiraz_constant_is_not_a_decision():
    assert pilot.INCOMING_TYPE_ITIRAZ not in pilot.ALLOWED_DECISIONS
    assert pilot.INCOMING_TYPE_ITIRAZ == "itiraz"


def test_case_id_is_deterministic_and_encodes_the_decision():
    assert pilot._case_id("tam_kabul", 3) == "GKC-TAM_KABUL-003"
    assert pilot._case_id("tam_kabul", 3) == pilot._case_id("tam_kabul", 3)


@pytest.mark.parametrize("decision", sorted(pilot.ALLOWED_DECISIONS))
def test_case_id_accepts_every_allowed_decision(decision):
    case_id = pilot._case_id(decision, 1)
    assert case_id.startswith("GKC-")
    assert decision.upper() in case_id


def test_scrub_reported_names_masks_every_residual_occurrence():
    text = "Başvuran Mehmet Demir, komşusu Mehmet Demir'in şikayetine cevap verdi."

    scrubbed = pilot._scrub_reported_names(text, ["Mehmet Demir"])

    assert "Mehmet" not in scrubbed
    assert scrubbed.count("[KİŞİ ADI]") == 2


def test_scrub_reported_names_handles_turkish_possessive_suffix():
    text = "Ayşe Yılmaz'ın dilekçesi incelendi."

    scrubbed = pilot._scrub_reported_names(text, ["Ayşe Yılmaz"])

    assert "Ayşe" not in scrubbed
    assert scrubbed == "[KİŞİ ADI] dilekçesi incelendi."


def test_scrub_reported_names_ignores_names_shorter_than_two_characters():
    text = "A harfiyle başlayan bir cümle."

    scrubbed = pilot._scrub_reported_names(text, ["A", ""])

    assert scrubbed == text


def test_scrub_reported_organizations_masks_private_legal_entity_names():
    text = "Başvuru Mavi Ufuk Enerji A.Ş. adına yapılmıştır."

    scrubbed = pilot._scrub_reported_organizations(text, ["Mavi Ufuk Enerji A.Ş."])

    assert "Mavi Ufuk" not in scrubbed
    assert "[KURUM ADI]" in scrubbed


def test_public_institutions_are_not_treated_as_private_organizations():
    organizations = ["Sivas Valiliği", "Mavi Ufuk Enerji A.Ş."]

    assert pilot._private_organization_names(organizations) == [
        "Mavi Ufuk Enerji A.Ş."
    ]


def test_collect_placeholders_does_not_capture_json_container_brackets():
    value = {
        "required_facts": [{"deger": "[KİŞİ ADI]"}],
        "must_not_invent": ["belirtilmeyen bir tarih"],
    }

    assert pilot._collect_placeholders(value) == ["[KİŞİ ADI]"]


def test_content_gate_accepts_only_traceable_verbatim_fields():
    codes = pilot._content_validation_codes(
        decision="eksik_belge",
        incoming_document=(
            "Başvuru 12.03.2026 tarihinde yapılmıştır. "
            "Dosya numarası E-2026/42 olarak bildirilmiştir."
        ),
        gold_draft=(
            "Başvurunuz 12.03.2026 tarihinde yapılmıştır. "
            "E-2026/42 numaralı dosya incelenmiştir. "
            "Kimlik fotokopisini sunmanız gerekmektedir."
        ),
        required_facts=[
            {
                "alan": "başvuru tarihi",
                "deger": "12.03.2026",
                "kaynak_satir": "Başvuru 12.03.2026 tarihinde yapılmıştır.",
            },
            {
                "alan": "dosya numarası",
                "deger": "E-2026/42",
                "kaynak_satir": "Dosya numarası E-2026/42 olarak bildirilmiştir.",
            },
        ],
        missing_information=[{"alan": "kimlik fotokopisi", "neden": "dosyada yok"}],
        expected_questions=["Kimlik fotokopisini sunabilir misiniz?"],
        must_include=[
            "E-2026/42 numaralı dosya incelenmiştir.",
            "Kimlik fotokopisini sunmanız gerekmektedir.",
        ],
        must_not_invent=["gelen evrakta olmayan karar numarası"],
    )

    assert codes == []


def test_content_gate_rejects_paraphrased_source_and_empty_required_lists():
    codes = pilot._content_validation_codes(
        decision="belirsiz_basvuru",
        incoming_document="Başvuru 12.03.2026 tarihinde yapılmıştır.",
        gold_draft="Başvurunuz incelenmiştir.",
        required_facts=[
            {
                "alan": "başvuru tarihi",
                "deger": "12.03.2026",
                "kaynak_satir": "Başvuru ... tarihinde yapılmıştır.",
            }
        ],
        missing_information=[],
        expected_questions=[],
        must_include=["Ek açıklama sununuz."],
        must_not_invent=[],
    )

    assert "kaynak_satir_bulunamadi" in codes
    assert "olgu_taslagina_tasinmadi" in codes
    assert "must_include_eksik" in codes
    assert "eksik_bilgi_listesi_bos" in codes
    assert "beklenen_soru_listesi_bos" in codes


def test_must_not_invent_alignment_removes_existing_facts_and_gate_rejects_hallucination():
    incoming = "Başvuru numarası E-2026/42 olarak bildirilmiştir."
    forbidden = pilot._align_must_not_invent(
        incoming,
        ["E-2026/42", "E-2026/999", "gerçekte belirtilmeyen bir karar tarihi"],
    )

    assert "E-2026/42" not in forbidden
    assert "E-2026/999" in forbidden

    codes = pilot._content_validation_codes(
        decision="tam_kabul",
        incoming_document=incoming,
        gold_draft="E-2026/999 sayılı işlem tesis edilmiştir. Talep kabul edilmiştir.",
        required_facts=[
            {
                "alan": "başvuru numarası",
                "deger": "E-2026/42",
                "kaynak_satir": incoming,
            },
            {
                "alan": "başvuru",
                "deger": "Başvuru",
                "kaynak_satir": incoming,
            },
        ],
        missing_information=[],
        expected_questions=[],
        must_include=["işlem tesis edilmiştir", "Talep kabul edilmiştir"],
        must_not_invent=forbidden,
    )

    assert "must_not_invent_ihlali" in codes


def test_draft_citation_contract_requires_matching_structured_article():
    draft = "4982 sayılı Bilgi Edinme Hakkı Kanunu'nun 27. maddesi uygulanmıştır."

    missing_article = pilot._draft_citation_contract_codes(
        draft,
        [{"type": "kanun", "number": "4982", "title": "BİLGİ EDİNME HAKKI KANUNU", "article": ""}],
    )
    matching_article = pilot._draft_citation_contract_codes(
        draft,
        [{"type": "kanun", "number": "4982", "title": "BİLGİ EDİNME HAKKI KANUNU", "article": "27"}],
    )

    assert "taslak_madde_yapisal_kayit_uyusmazligi" in missing_article
    assert matching_article == []


def test_draft_legal_reference_is_structured_before_mcp_verification():
    references = pilot._merge_draft_legal_references(
        "4982 sayılı Bilgi Edinme Hakkı Kanunu'nun 27. maddesi uygulanmıştır.",
        [],
    )

    assert [reference.model_dump() for reference in references] == [
        {
            "type": "kanun",
            "number": "4982",
            "title": "Bilgi Edinme Hakkı Kanunu",
            "article": "27",
        }
    ]


@pytest.mark.asyncio
async def test_recovered_draft_references_are_limited_to_numbers_in_draft():
    class _Client:
        async def generate_structured(self, **_kwargs):
            return pilot._ExtractedLegalBasis(
                references=[
                    pilot._LegalReference(
                        type="kanun", number="6698", title="Kişisel Verilerin Korunması Kanunu"
                    ),
                    pilot._LegalReference(
                        type="kanun", number="9999", title="Uydurma Kanun"
                    ),
                ]
            )

    references = await pilot._recover_missing_draft_references(
        _Client(), "6698 sayılı KVKK hükümleri uygulanmıştır.", []
    )

    assert [reference.number for reference in references] == ["6698"]


@pytest.mark.asyncio
async def test_quality_metadata_recovery_uses_a_structured_second_pass():
    expected = pilot._RecoveredQualityMetadata(
        required_facts=[
            pilot._RequiredFact(alan="tarih", deger="12.03.2026", kaynak_satir="Başvuru 12.03.2026 tarihinde yapılmıştır."),
            pilot._RequiredFact(alan="konu", deger="destek", kaynak_satir="Destek talep edilmiştir."),
        ],
        missing_information=[pilot._MissingInformation(alan="kimlik", neden="dosyada yok")],
        expected_questions=["Kimlik belgesini sunabilir misiniz?"],
        must_include=["eksik belge", "başvuru sonuçlandırılamamıştır"],
    )

    class _Client:
        async def generate_structured(self, **_kwargs):
            return expected

    recovered = await pilot._recover_quality_metadata(
        _Client(),
        decision="eksik_belge",
        incoming_document="Başvuru 12.03.2026 tarihinde yapılmıştır. Destek talep edilmiştir.",
        gold_draft="Eksik belge nedeniyle başvuru sonuçlandırılamamıştır.",
    )

    assert recovered == expected


@pytest.mark.asyncio
async def test_legal_relevance_judge_fails_closed_and_accepts_supported_article():
    class _Client:
        async def generate_structured(self, **_kwargs):
            return pilot._LegalRelevanceResult(relevant=True, reason_code="dogrudan_destek")

    assert await pilot._judge_legal_relevance(
        _Client(),
        requested_action="Bilgi talebi",
        decision_reason="Madde kapsamındaki bilgi verilir.",
        gold_draft="Bilgi verilmiştir.",
        official_reference={"number": "4982", "article": "11"},
        official_article_text="MADDE 11 - Kurumlar başvuruyu cevaplandırır.",
    )


@pytest.mark.asyncio
async def test_legal_relevance_judge_checks_title_only_references():
    class _Client:
        async def generate_structured(self, **kwargs):
            payload = kwargs["messages"][1]["content"]
            assert "BİLGİ EDİNME HAKKI KANUNU" in payload
            return pilot._LegalRelevanceResult(
                relevant=False, reason_code="konu_disi"
            )

    assert not await pilot._judge_legal_relevance(
        _Client(),
        requested_action="Kurs ücreti iadesi",
        decision_reason="Ücret iadesi uygun bulunmuştur.",
        gold_draft="Kurs ücreti iade edilmiştir.",
        official_reference={
            "number": "4982",
            "title": "BİLGİ EDİNME HAKKI KANUNU",
            "article": "",
        },
        official_article_text="",
    )


@pytest.mark.asyncio
async def test_draft_groundedness_judge_rejects_unsupported_claims():
    class _Client:
        async def generate_structured(self, **kwargs):
            assert kwargs["response_model"] is pilot._DraftGroundednessResult
            return pilot._DraftGroundednessResult(
                grounded=False,
                reason_code="desteksiz_sistem_kaydi",
                unsupported_claims=["Rapor 14.01.2026 tarihinde sisteme işlendi."],
            )

    assert not await pilot._judge_draft_groundedness(
        _Client(),
        incoming_document="Rapor 10.01.2026 tarihinde alınmıştır.",
        requested_action="Rapor durumunun bildirilmesi",
        decision="yalnizca_bilgilendirme",
        decision_reason="Mevcut durum bildirilecektir.",
        gold_draft="Rapor 14.01.2026 tarihinde sisteme işlenmiştir.",
    )


def test_chronology_gate_rejects_one_year_response_jump():
    codes = pilot._chronology_validation_codes(
        "Başvuru 18.02.2025 tarihinde yapılmıştır. E-2025/8890 sayılıdır.",
        "Cevap tarihi 25.02.2026 ve sayısı E-2026/1123'tür.",
    )

    assert codes == [
        "taslak_evrak_yili_gecersiz",
        "taslak_tarih_kronolojisi_gecersiz",
    ]


def test_chronology_gate_allows_prompt_response_date():
    assert pilot._chronology_validation_codes(
        "Başvuru 18.02.2025 tarihinde yapılmıştır.",
        "Cevap tarihi 25.02.2025 ve sayısı E-2025/1123'tür.",
    ) == []


def test_chronology_gate_rejects_impossible_calendar_date():
    assert pilot._chronology_validation_codes(
        "Başvuru 18.02.2026 tarihinde yapılmıştır.",
        "Cevap tarihi 30.02.2026'dır.",
    ) == ["taslak_takvim_tarihi_gecersiz"]


def test_chronology_gate_rejects_multiple_new_operational_dates():
    assert pilot._chronology_validation_codes(
        "Başvuru 20.05.2026 tarihinde yapılmıştır.",
        (
            "Cevap tarihi 28.05.2026'dır. Dosya 22.05.2026 tarihinde sevk "
            "edilmiş ve 26.05.2026 tarihinde kurul gündemine alınmıştır."
        ),
    ) == ["taslak_desteksiz_ek_tarih"]


def test_metropolitan_special_administration_is_rejected():
    assert pilot._institution_plausibility_codes(
        "T.C.\nMERSİN İL ÖZEL İDARESİ",
        "Mersin İl Özel İdaresi tarafından işlem yapılmıştır.",
    ) == ["kaldirilmis_buyuksehir_il_ozel_idaresi"]


def test_unsupported_numeric_claims_are_rejected():
    assert pilot._unsupported_numeric_claim_codes(
        "Başvuruda 300.000,00 TL talep edilmiştir.",
        (
            "300.000,00 TL kabul edilmiştir. Üretimin %50 olduğu ve ödemenin "
            "30 iş günü içinde yapılacağı değerlendirilmiştir."
        ),
    ) == ["taslak_desteksiz_gun_suresi", "taslak_desteksiz_yuzde"]


@pytest.mark.asyncio
async def test_institution_competence_judge_fails_closed():
    class _Client:
        async def generate_structured(self, **kwargs):
            assert kwargs["response_model"] is pilot._InstitutionCompetenceResult
            return pilot._InstitutionCompetenceResult(
                valid=False, reason_code="kaldirilmis_kurum"
            )

    assert not await pilot._judge_institution_competence(
        _Client(),
        institution="MERSİN İL ÖZEL İDARESİ",
        incoming_document="Araç çevre testi hakkında başvuru.",
        decision="yalnizca_bilgilendirme",
        decision_reason="Süreç bildirilecektir.",
        gold_draft="Ruhsat süreci devam etmektedir.",
    )


@pytest.mark.asyncio
async def test_combined_quality_review_uses_one_structured_call():
    class _Client:
        calls = 0

        async def generate_structured(self, **kwargs):
            self.calls += 1
            assert kwargs["response_model"] is pilot._CaseQualityReviewResult
            return pilot._CaseQualityReviewResult(
                grounded=True,
                institution_valid=True,
                reason_code="uygun",
                unsupported_claims=[],
            )

    client = _Client()
    result = await pilot._review_case_quality(
        client,
        institution="İZMİR VALİLİĞİ",
        incoming_document="Başvuru 01.02.2026 tarihinde yapılmıştır.",
        requested_action="Bilgi talebi",
        decision="yalnizca_bilgilendirme",
        decision_reason="Mevcut durum bildirilecektir.",
        gold_draft="Başvurunuz hakkında mevcut durum bildirilmiştir.",
    )

    assert client.calls == 1
    assert result and result.grounded and result.institution_valid


def test_uncovered_number_citation_becomes_official_resolution_candidate():
    references = pilot._add_uncovered_number_references(
        "6698 sayılı KVKK ile 4982 sayılı Kanun hükümleri uygulanmıştır.", []
    )

    assert [(reference.number, reference.title) for reference in references] == [
        ("6698", ""),
        ("4982", ""),
    ]


def test_document_number_is_not_mistaken_for_legislation_number():
    text = (
        "12.02.2026 tarihli ve 45678 sayılı onay yazısı incelenmiştir. "
        "4982 sayılı Bilgi Edinme Hakkı Kanunu uygulanmıştır."
    )

    assert [match.group("number") for match in pilot._DRAFT_LAW_NUMBER.finditer(text)] == [
        "4982"
    ]


def test_repair_checkpoint_filters_false_forbidden_facts_and_quarantines_hallucination():
    base = {
        "case_id": "GKC-TAM_KABUL-008",
        "decision": "tam_kabul",
        "incoming_document": "Başvuru E-2026/42 sayısıyla yapılmıştır.",
        "gold_draft": "E-2026/42 sayılı başvuru kabul edilmiştir. İşlem tamamlanmıştır.",
        "required_facts": [
            {"alan": "sayı", "deger": "E-2026/42", "kaynak_satir": "Başvuru E-2026/42 sayısıyla yapılmıştır."},
            {"alan": "işlem", "deger": "Başvuru", "kaynak_satir": "Başvuru E-2026/42 sayısıyla yapılmıştır."},
        ],
        "missing_information": [],
        "expected_questions": [],
        "must_include": ["başvuru kabul edilmiştir", "İşlem tamamlanmıştır"],
        "must_not_invent": ["E-2026/42"],
        "provenance": {"kurum_tahmini": "İZMİR VALİLİĞİ"},
    }
    bad = pilot.json.loads(pilot.json.dumps(base, ensure_ascii=False))
    bad["case_id"] = "GKC-TAM_KABUL-009"
    bad["gold_draft"] += " E-2026/999 sayılı yeni işlem kurulmuştur."
    bad["must_not_invent"].append("E-2026/999")

    accepted, rejected = pilot._repair_checkpoint_cases([base, bad])

    assert [case["case_id"] for case in accepted] == ["GKC-TAM_KABUL-008"]
    assert accepted[0]["must_not_invent"] == []
    assert [record["case_id"] for record in rejected] == ["GKC-TAM_KABUL-009"]
    assert "must_not_invent_ihlali" in rejected[0]["basarisizlik_kategorileri"]


def test_repair_checkpoint_keeps_latest_duplicate_and_archives_older_one():
    older = {
        "case_id": "GKC-TAM_KABUL-008",
        "decision": "tam_kabul",
        "incoming_document": "Başvuru E-2026/42 sayısıyla yapılmıştır.",
        "gold_draft": "E-2026/42 sayılı başvuru kabul edilmiştir. İşlem tamamlanmıştır.",
        "required_facts": [
            {"alan": "sayı", "deger": "E-2026/42", "kaynak_satir": "Başvuru E-2026/42 sayısıyla yapılmıştır."},
            {"alan": "işlem", "deger": "Başvuru", "kaynak_satir": "Başvuru E-2026/42 sayısıyla yapılmıştır."},
        ],
        "missing_information": [],
        "expected_questions": [],
        "must_include": ["başvuru kabul edilmiştir", "İşlem tamamlanmıştır"],
        "must_not_invent": [],
        "legal_basis": [],
        "provenance": {"kurum_tahmini": "İZMİR VALİLİĞİ"},
        "version": "older",
    }
    latest = pilot.json.loads(pilot.json.dumps(older, ensure_ascii=False))
    latest["version"] = "latest"

    accepted, rejected = pilot._repair_checkpoint_cases([older, latest])

    assert [case["version"] for case in accepted] == ["latest"]
    assert rejected[0]["basarisizlik_kategorileri"] == [
        "tekrar_case_id_eski_checkpoint"
    ]


def test_partition_manual_rejections_preserves_case_and_reason():
    cases = [{"case_id": "GKC-RET-001"}, {"case_id": "GKC-RET-002"}]

    accepted, rejected, found = pilot._partition_manual_rejections(
        cases, {"GKC-RET-002": "karar_anlami_uyusmazligi"}
    )

    assert accepted == [{"case_id": "GKC-RET-001"}]
    assert found == {"GKC-RET-002"}
    assert rejected[0]["case"] == {"case_id": "GKC-RET-002"}
    assert rejected[0]["manuel_ret_nedeni"] == "karar_anlami_uyusmazligi"


def test_align_traceability_repairs_source_lines_and_drops_false_claims():
    facts, must_include = pilot._align_traceability_fields(
        incoming_document=(
            "Başvuru 12.03.2026 tarihinde yapılmıştır.\n"
            "Dosya numarası E-2026/42 olarak bildirilmiştir."
        ),
        gold_draft=(
            "12.03.2026 tarihli ve E-2026/42 numaralı başvurunuz kabul edilmiştir."
        ),
        required_facts=[
            {
                "alan": "başvuru tarihi",
                "deger": "12.03.2026",
                "kaynak_satir": "Başvuru ... tarihinde yapılmıştır.",
            },
            {
                "alan": "dosya numarası",
                "deger": "E-2026/42",
                "kaynak_satir": "Dosya numarası E-2026/42 olarak bildirilmiştir.",
            },
            {
                "alan": "uydurma",
                "deger": "99.99.2099",
                "kaynak_satir": "Kaynakta yoktur.",
            },
        ],
        must_include=["başvurunuz kabul edilmiştir", "taslakta olmayan ifade"],
    )

    assert len(facts) == 2
    assert facts[0]["kaynak_satir"] == "Başvuru 12.03.2026 tarihinde yapılmıştır."
    assert must_include == ["başvurunuz kabul edilmiştir"]


# --- Aşama 3.2: mevzuat doğrulamasının üretim hattındaki sözleşmesi ----


class _SahteDogrulayici:
    """``MevzuatDogrulayici`` yerine geçer; MCP'ye hiç gitmez."""

    def __init__(self, gecerli_numaralar: set[str]) -> None:
        self.gecerli_numaralar = gecerli_numaralar
        self.sorulan: list[str] = []

    async def dogrula(self, atif):
        self.sorulan.append(atif.numara)
        if atif.numara in self.gecerli_numaralar:
            return _gecerli_sonuc(atif)
        return _gecersiz_sonuc()


def _gecerli_sonuc(atif):
    from mevzuat_dogrulama import DogrulamaSonucu

    return DogrulamaSonucu(
        True,
        resmi_baslik="BİLGİ EDİNME HAKKI KANUNU",
        mevzuat_id="103705",
        kanonik_tur="kanun",
        kayit={
            "type": "kanun",
            "number": atif.numara,
            "title": "BİLGİ EDİNME HAKKI KANUNU",
            "article": atif.madde,
            "verification_source": "mevzuat-mcp:103705",
            "verification_status": "dogrulandi",
        },
    )


def _gecersiz_sonuc():
    from mevzuat_dogrulama import DogrulamaSonucu

    return DogrulamaSonucu(False, "baslik_uyusmazligi:kanun/5615")


def _sahte_llm(monkeypatch, legal_basis):
    """``_generate_one``'ın Evren çağrısını sabit bir çıktıyla değiştirir."""
    case = pilot._GeneratedCase(
        incoming_document=(
            "T.C.\nİZMİR VALİLİĞİ\n\nSayı: E-2026/1\n\n"
            "Başvuru 12.03.2026 tarihinde yapılmıştır. "
            "Belge örneği talebi ekte sunulmuştur."
        ),
        incoming_type="dilekce",
        requested_action="Belge örneği talebi",
        decision_reason="Talep mevzuata uygundur.",
        outgoing_correspondence_type="cevap_yazisi",
        required_facts=[
            pilot._RequiredFact(
                alan="başvuru tarihi",
                deger="12.03.2026",
                kaynak_satir="Başvuru 12.03.2026 tarihinde yapılmıştır.",
            ),
            pilot._RequiredFact(
                alan="talep türü",
                deger="Belge örneği",
                kaynak_satir="Belge örneği talebi ekte sunulmuştur.",
            ),
        ],
        gold_draft=(
            "T.C.\nİZMİR VALİLİĞİ\n\n12.03.2026 tarihli belge örneği talebiniz "
            "uygun görülmüştür."
        ),
        must_include=["belge örneği talebiniz", "uygun görülmüştür"],
        must_not_invent=["gerçekte belirtilmeyen bir evrak sayısı"],
        legal_basis=legal_basis,
        used_person_names=[],
    )

    class _Client:
        async def generate_structured(self, **kwargs):
            if kwargs.get("response_model") is pilot._LegalRelevanceResult:
                return pilot._LegalRelevanceResult(
                    relevant=True, reason_code="test_dogrudan_destek"
                )
            if kwargs.get("response_model") is pilot._DraftGroundednessResult:
                return pilot._DraftGroundednessResult(
                    grounded=True,
                    reason_code="test_olgular_destekli",
                    unsupported_claims=[],
                )
            if kwargs.get("response_model") is pilot._InstitutionCompetenceResult:
                return pilot._InstitutionCompetenceResult(
                    valid=True, reason_code="test_kurum_uygun"
                )
            if kwargs.get("response_model") is pilot._CaseQualityReviewResult:
                return pilot._CaseQualityReviewResult(
                    grounded=True,
                    institution_valid=True,
                    reason_code="test_uygun",
                    unsupported_claims=[],
                )
            return case

    monkeypatch.setattr(pilot, "get_llm_client", lambda **_kwargs: _Client())


@pytest.mark.asyncio
async def test_generate_one_rejects_a_case_whose_citation_fails_verification(monkeypatch):
    """Aşama 3.2'nin sözleşmesi: doğrulanamayan TEK bir atıf, kusursuz olsa
    bile tüm vakayı geçersiz kılar ve reddedilen atıf bir sonraki denemeye
    geri bildirilmek üzere döndürülür."""
    _sahte_llm(
        monkeypatch,
        [pilot._LegalReference(type="kanun", number="5615", title="Sosyal Yardımlaşma Kanunu")],
    )

    case, reason, rejected = await pilot._generate_one(
        "tam_kabul",
        pilot.TARGET_DECISIONS["tam_kabul"],
        1,
        dogrulayici=_SahteDogrulayici(set()),
    )

    assert case is None
    assert reason.startswith("mevzuat_dogrulanamadi")
    assert rejected == ["kanun 5615 (Sosyal Yardımlaşma Kanunu)"]


@pytest.mark.asyncio
async def test_generate_one_stores_the_official_title_not_the_llm_claim(monkeypatch):
    """Vakaya yazılan başlık, modelin iddiası değil MCP'den gelen resmî
    addır -- aksi halde doğrulama, yanlış metni veri setinde bırakırdı."""
    _sahte_llm(
        monkeypatch,
        [pilot._LegalReference(type="kanun", number="4982", title="bilgi edinme kanunu")],
    )

    case, reason, _ = await pilot._generate_one(
        "tam_kabul",
        pilot.TARGET_DECISIONS["tam_kabul"],
        1,
        dogrulayici=_SahteDogrulayici({"4982"}),
    )

    assert reason == ""
    assert case["legal_basis"] == [
        {
            "type": "kanun",
            "number": "4982",
            "title": "BİLGİ EDİNME HAKKI KANUNU",
            "article": "",
            "verification_source": "mevzuat-mcp:103705",
            "verification_status": "dogrulandi",
        }
    ]
    assert case["legal_basis_text"] == ["4982 sayılı BİLGİ EDİNME HAKKI KANUNU"]


@pytest.mark.asyncio
async def test_generate_one_accepts_a_case_with_no_citation_at_all(monkeypatch):
    """Resmî yazışmaların çoğu mevzuat atfı içermez; boş liste bir
    başarısızlık değildir ve hiç MCP çağrısı doğurmaz."""
    _sahte_llm(monkeypatch, [])
    dogrulayici = _SahteDogrulayici(set())

    case, reason, _ = await pilot._generate_one(
        "tam_kabul", pilot.TARGET_DECISIONS["tam_kabul"], 1, dogrulayici=dogrulayici
    )

    assert reason == ""
    assert case["legal_basis"] == []
    assert dogrulayici.sorulan == []


@pytest.mark.asyncio
async def test_generate_one_masks_pii_in_all_free_text_metadata(monkeypatch):
    _sahte_llm(monkeypatch, [])
    original_factory = pilot.get_llm_client
    client = original_factory(provider="evren", model="ignored", temperature=0.8)
    generated = await client.generate_structured()
    generated.used_person_names = ["Mehmet Demir"]
    generated.requested_action = "Mehmet Demir adına belge örneği talebi"
    generated.required_facts[0].deger = "Mehmet Demir"
    generated.required_facts[0].kaynak_satir = "Başvuran Mehmet Demir'dir."
    generated.incoming_document += " Başvuran Mehmet Demir'dir."
    generated.gold_draft += " Başvuran Mehmet Demir adına işlem yapılmıştır."

    class _Client:
        async def generate_structured(self, **kwargs):
            if kwargs.get("response_model") is pilot._DraftGroundednessResult:
                return pilot._DraftGroundednessResult(
                    grounded=True, reason_code="test_uygun", unsupported_claims=[]
                )
            if kwargs.get("response_model") is pilot._InstitutionCompetenceResult:
                return pilot._InstitutionCompetenceResult(
                    valid=True, reason_code="test_kurum_uygun"
                )
            if kwargs.get("response_model") is pilot._CaseQualityReviewResult:
                return pilot._CaseQualityReviewResult(
                    grounded=True,
                    institution_valid=True,
                    reason_code="test_uygun",
                    unsupported_claims=[],
                )
            return generated

    monkeypatch.setattr(pilot, "get_llm_client", lambda **_kwargs: _Client())

    case, reason, _ = await pilot._generate_one(
        "tam_kabul", pilot.TARGET_DECISIONS["tam_kabul"], 8,
        dogrulayici=_SahteDogrulayici(set()),
    )

    assert reason == ""
    assert "Mehmet Demir" not in pilot.json.dumps(case, ensure_ascii=False)
    assert case["requested_action"].startswith("[KİŞİ ADI]")


@pytest.mark.asyncio
async def test_generate_one_masks_reported_organizations_everywhere(monkeypatch):
    _sahte_llm(monkeypatch, [])
    original_factory = pilot.get_llm_client
    client = original_factory(provider="evren", model="ignored", temperature=0.8)
    generated = await client.generate_structured()
    generated.used_organization_names = ["Mavi Ufuk Enerji A.Ş."]
    generated.incoming_document += " Başvuran Mavi Ufuk Enerji A.Ş.'dir."
    generated.gold_draft += " Mavi Ufuk Enerji A.Ş. adına işlem yapılmıştır."
    generated.requested_action = "Mavi Ufuk Enerji A.Ş. adına belge örneği talebi"

    class _Client:
        async def generate_structured(self, **kwargs):
            if kwargs.get("response_model") is pilot._DraftGroundednessResult:
                return pilot._DraftGroundednessResult(
                    grounded=True, reason_code="test_uygun", unsupported_claims=[]
                )
            if kwargs.get("response_model") is pilot._InstitutionCompetenceResult:
                return pilot._InstitutionCompetenceResult(
                    valid=True, reason_code="test_kurum_uygun"
                )
            if kwargs.get("response_model") is pilot._CaseQualityReviewResult:
                return pilot._CaseQualityReviewResult(
                    grounded=True,
                    institution_valid=True,
                    reason_code="test_uygun",
                    unsupported_claims=[],
                )
            return generated

    monkeypatch.setattr(pilot, "get_llm_client", lambda **_kwargs: _Client())

    case, reason, _ = await pilot._generate_one(
        "tam_kabul",
        pilot.TARGET_DECISIONS["tam_kabul"],
        8,
        dogrulayici=_SahteDogrulayici(set()),
    )

    assert reason == ""
    serialized = pilot.json.dumps(case, ensure_ascii=False)
    assert "Mavi Ufuk" not in serialized
    assert "[KURUM ADI]" in serialized


@pytest.mark.asyncio
async def test_generate_one_rejects_wrong_incoming_type_for_itiraz_quota(monkeypatch):
    _sahte_llm(monkeypatch, [])

    case, reason, _ = await pilot._generate_one(
        "tam_kabul", pilot.TARGET_DECISIONS["tam_kabul"], 1,
        dogrulayici=_SahteDogrulayici(set()), force_itiraz=True,
    )

    assert case is None
    assert reason == "incoming_type_itiraz_bekleniyor"


def test_few_shots_carry_traceable_provenance():
    examples = pilot._load_few_shots(
        pilot.TARGET_DECISIONS["tam_kabul"]["few_shot_glob"], 1
    )

    assert examples[0].card_id
    assert examples[0].source_path.endswith(".md")
    assert len(examples[0].card_sha256) == 64
    assert len(examples[0].source_group) == 16


def test_rejected_refs_are_fed_back_into_the_retry_prompt():
    """Sıcaklık 0.8'de bile model aynı yanlış numara/ad eşleşmesini ısrarla
    üretebilir; reddedilen atıf prompt'a geri yazılmazsa üç deneme de aynı
    hatayı tekrarlar."""
    examples = [pilot.FewShotExample("Örnek", "cevap_yazisi", "gövde")]

    messages = pilot._build_messages(
        "ret",
        pilot.TARGET_DECISIONS["ret"],
        examples,
        rejected_refs=["kanun 5615 (Sosyal Yardımlaşma Kanunu)"],
    )

    assert "5615" in messages[-1]["content"]
    assert "TEKRAR KULLANMA" in messages[-1]["content"]


def test_quality_gate_feedback_is_fed_back_into_retry_prompt():
    examples = [pilot.FewShotExample("Örnek", "cevap_yazisi", "gövde")]

    messages = pilot._build_messages(
        "kismi_kabul",
        pilot.TARGET_DECISIONS["kismi_kabul"],
        examples,
        quality_feedback=["taslak_mevzuat_yapisal_kayit_yok"],
    )

    assert "İÇERİK KAPISINDAN GEÇMEDİ" in messages[-1]["content"]
    assert "taslak_mevzuat_yapisal_kayit_yok" in messages[-1]["content"]


def test_deterministic_blueprint_is_binding_in_prompt():
    examples = [pilot.FewShotExample("Örnek", "cevap_yazisi", "gövde")]
    blueprint = pilot.DETERMINISTIC_PROTOTYPES["GKC-EKSIK_BELGE-003"]

    messages = pilot._build_messages(
        "eksik_belge",
        pilot.TARGET_DECISIONS["eksik_belge"],
        examples,
        deterministic_blueprint=blueprint,
    )

    content = messages[-1]["content"]
    assert "DETERMİNİSTİK İSKELET" in content
    assert blueprint["institution"] in content
    assert blueprint["decision_reason"] in content
    assert "Yalnız incoming_document ve gold_draft" in content


def test_blueprint_facts_are_bound_to_exact_source_lines():
    incoming = "Konu: Diploma\n12.06.2021 tarihli diplomam için soyadı düzeltme talep ederim."

    facts = pilot._blueprint_required_facts(
        incoming,
        [("diploma_tarihi", "12.06.2021"), ("talep", "soyadı düzeltme")],
    )

    assert facts[0]["kaynak_satir"] == facts[1]["kaynak_satir"]
    assert facts[0]["deger"] == "12.06.2021"


@pytest.mark.asyncio
async def test_parallel_run_limits_concurrency_and_centralizes_writes(
    monkeypatch, tmp_path
):
    active = 0
    maximum_active = 0

    async def fake_generate(decision, _spec, index, **_kwargs):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        case_id = pilot._case_id(decision, index)
        return (
            {
                "case_id": case_id,
                "incoming_document": f"T.C.\nİZMİR VALİLİĞİ\n{case_id}",
                "provenance": {"kurum_tahmini": "İZMİR VALİLİĞİ"},
                "legal_basis": [],
            },
            "",
            [],
        )

    monkeypatch.setattr(pilot, "_generate_one", fake_generate)
    monkeypatch.setattr(pilot, "MAIN_ROOT", tmp_path)
    monkeypatch.setattr(pilot, "MAIN_OUTPUT", tmp_path / "vakalar.jsonl")
    monkeypatch.setattr(pilot, "MAIN_ERRORS", tmp_path / "hatalar.jsonl")

    cases = await pilot._run_parallel(
        apply=True,
        resume=False,
        max_cases=5,
        max_retries=1,
        concurrency=2,
    )

    assert len(cases) == 5
    assert maximum_active == 2
    assert len((tmp_path / "vakalar.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    benchmark = json.loads(
        (tmp_path / "son-paralel-benchmark.json").read_text(encoding="utf-8")
    )
    assert benchmark["requested"] == 5
    assert benchmark["accepted"] == 5
    assert benchmark["concurrency"] == 2
