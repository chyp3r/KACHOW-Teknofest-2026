"""Unit tests for draft_graph._build_brief's grounding of incoming-document
identity fields.

The bug this guards against: the incoming document's own Sayı/Tarih used to
be rendered as plain "Sayı: ..." lines indistinguishable from the response's
own transferable fields (Konu, Muhatap, ...), so the writer copied the
*incoming* document's case number into the *outgoing* response as if it were
its own -- a response letter must carry its own institution's number
(assigned at send time, hence a placeholder), never the number of the
document it is replying to.
"""

from app.ai.identity.company_profile import CompanyProfile
from app.ai.workflows.draft_graph import _build_brief

CLASSIFICATION = {
    "document_type_label": "Resmî Yazı",
    "summary": "Personel izin talebi.",
    "fields": {
        "sayi": "E-2026-998877",
        "tarih": "01.01.2026",
        "konu": "Personel İzin Talebi",
        "muhatap": "İnsan Kaynakları Daire Başkanlığı",
        "gonderen_kurum": "Hukuk İşleri Müdürlüğü",
        "imza_sahibi": "Ali Veli",
        "imza_unvani": "Genel Müdür",
    },
    "missing_fields": [],
}


def test_the_incoming_documents_own_number_is_labeled_as_reference_only():
    brief = _build_brief(CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.")

    assert "GELEN EVRAKIN KİMLİK BİLGİLERİ" in brief
    assert "E-2026-998877" in brief
    # The label must make explicit this is reference-only material, not a
    # value to copy into the response's own Sayı/Tarih line.
    assert "İlgi" in brief
    assert "ASLA yazma" in brief or "asla yazma" in brief.lower()


def test_transferable_fields_are_not_folded_into_the_identity_section():
    brief = _build_brief(CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.")

    identity_section, _, rest = brief.partition("4. Diğer Çıkarılan Bilgiler")
    assert "İnsan Kaynakları Daire Başkanlığı" not in identity_section
    assert "Personel İzin Talebi" not in identity_section
    assert "İnsan Kaynakları Daire Başkanlığı" in rest
    assert "Personel İzin Talebi" in rest


def test_today_is_rendered_as_section_zero_and_never_asked_about():
    brief = _build_brief(
        CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.", today="18.08.2026"
    )

    assert "0. BUGÜNÜN TARİHİ: 18.08.2026" in brief
    assert "AYNEN yaz" in brief


def test_missing_today_falls_back_to_a_placeholder_note():
    brief = _build_brief(CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.")

    assert "0. BUGÜNÜN TARİHİ: (bilinmiyor" in brief


def test_a_missing_incoming_number_still_renders_the_identity_section():
    classification = {**CLASSIFICATION, "fields": {**CLASSIFICATION["fields"], "sayi": None}}

    brief = _build_brief(classification, context="", instructions="Cevap yazısı hazırla.")

    assert "GELEN EVRAKIN KİMLİK BİLGİLERİ" in brief


# ==========================================
# entities -- the "CV'de çalıştığı kurumları belirt" bug: document analysis
# already extracts a flat list of important names (person/institution/date/
# amount, see EvrakField.entities) but this module never read it, so the
# writer had no way to answer a request naming something only that list
# (not the structured sayi/konu/muhatap/... fields) carried.
# ==========================================
def test_detected_entities_are_rendered_into_the_brief():
    classification = {
        **CLASSIFICATION,
        "entities": ["ACME Yazılım A.Ş.", "Beta Danışmanlık Ltd.", "Ahmet Yılmaz"],
    }

    brief = _build_brief(classification, context="", instructions="Cevap yazısı hazırla.")

    assert "ACME Yazılım A.Ş." in brief
    assert "Beta Danışmanlık Ltd." in brief
    assert "Ahmet Yılmaz" in brief


def test_entities_are_rendered_as_grounding_material_not_asked_about():
    """The whole point: the brief must tell the writer to look here instead
    of leaving a placeholder that turns into a question the document itself
    already answers."""
    classification = {**CLASSIFICATION, "entities": ["Gamma Holding"]}

    brief = _build_brief(classification, context="", instructions="Cevap yazısı hazırla.")

    assert "kullanıcıya SORMA" in brief


def test_no_detected_entities_renders_a_clean_placeholder_not_a_crash():
    brief = _build_brief(CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.")
    assert "(tespit edilmedi)" in brief


def test_a_non_list_entities_value_degrades_to_the_placeholder():
    classification = {**CLASSIFICATION, "entities": None}
    brief = _build_brief(classification, context="", instructions="Cevap yazısı hazırla.")
    assert "(tespit edilmedi)" in brief


# ==========================================
# KURUM KİMLİĞİ -- company identity (#214)
# ==========================================
def test_no_profile_renders_no_identity_section():
    brief = _build_brief(CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.")
    assert "KURUM KİMLİĞİ" not in brief


def test_empty_profile_renders_no_identity_section():
    brief = _build_brief(
        CLASSIFICATION,
        context="",
        instructions="Cevap yazısı hazırla.",
        profile=CompanyProfile.empty("company-1"),
    )
    assert "KURUM KİMLİĞİ" not in brief


def test_configured_profile_renders_the_identity_section():
    profile = CompanyProfile(
        company_id="company-1",
        display_name="Acme A.Ş.",
        letterhead="T.C.\nACME A.Ş.",
        default_signer_title="Daire Başkanı",
    )
    brief = _build_brief(
        CLASSIFICATION, context="", instructions="Cevap yazısı hazırla.", profile=profile
    )
    assert "KURUM KİMLİĞİ" in brief
    assert "Acme A.Ş." in brief
    assert "Daire Başkanı" in brief
    assert "Yazım Briefi" in brief.split("KURUM KİMLİĞİ")[1]
