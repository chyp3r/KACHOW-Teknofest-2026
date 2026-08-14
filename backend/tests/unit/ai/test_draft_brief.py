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


def test_a_missing_incoming_number_still_renders_the_identity_section():
    classification = {**CLASSIFICATION, "fields": {**CLASSIFICATION["fields"], "sayi": None}}

    brief = _build_brief(classification, context="", instructions="Cevap yazısı hazırla.")

    assert "GELEN EVRAKIN KİMLİK BİLGİLERİ" in brief
