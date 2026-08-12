"""Unit tests for the Markdown-first official-correspondence preparation."""

import os
import sys
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import prepare_resmi_yazisma_markdown as prepare  # noqa: E402


def test_front_matter_round_trip_preserves_colons_and_turkish_text():
    original = {
        "id": "BEL-001",
        "kategori": "diger_resmi_yazisma",
        "baslik": "Encümen Kararı: 2026/42",
        "rag_status": "candidate",
    }

    meta, body = prepare.split_front_matter(prepare.render_card(original, "# Başlık\n\nGövde."))

    assert meta == original
    assert body == "# Başlık\n\nGövde."


def test_semantic_anonymization_uses_context_instead_of_deleted_marker():
    text = (
        "Sayı: E-[SİLİNMİŞTİR]\n"
        "Başvuran: [SİLİNMİŞTİR]\n"
        "Telefon: 0532 123 45 67\n"
        "E-posta: ad.soyad@example.org\n"
        "[SİLİNMİŞTİR]\nDaire Başkanı"
    )

    anonymized = prepare.semantic_anonymize(text)

    assert "[SİLİNMİŞTİR]" not in anonymized
    assert "**Sayı:** [EVRAK SAYISI]" in anonymized
    assert "Başvuran: [KİŞİ ADI]" in anonymized
    assert "[KURUM İLETİŞİM BİLGİLERİ]" in anonymized
    assert "E-posta: [E-POSTA]" in anonymized
    assert "[İMZA SAHİBİ]\nDaire Başkanı" in anonymized


def test_bold_number_and_subject_on_one_line_are_preserved_as_two_fields():
    text = "**Sayı:** E-[SİLİNMİŞTİR] **Konu:** Bütçe Ödeneği Aktarımı"

    anonymized = prepare.semantic_anonymize(text)

    assert anonymized == "**Sayı:** [EVRAK SAYISI]\n**Konu:** Bütçe Ödeneği Aktarımı"


def test_semantic_anonymization_masks_generated_personal_data():
    text = "Ahmet Yılmaz (TCKN: 12345678901) adlı kişinin adresi.\nAdres: Test Mah. No: 3"

    anonymized = prepare.semantic_anonymize(text)

    assert "Ahmet Yılmaz" not in anonymized
    assert "12345678901" not in anonymized
    assert "Test Mah." not in anonymized
    assert "[KİŞİ ADI]" in anonymized
    assert "[T.C. KİMLİK NO]" in anonymized
    assert "[ADRES]" in anonymized


def test_official_contact_lines_are_generalized_without_masking_legal_prose():
    text = (
        "Bilgi için: Altunser KARAKURUMER\n"
        "Güvenevler Mah. Kuzgun Cad. No:51 Aşağı Ayrancı/ANKARA\n"
        "Santral: (0312) 466 07 37\n"
        "Mahalle muhtarlarına ödenek ödenmesi hakkında görüş istenmiştir."
    )

    anonymized = prepare.semantic_anonymize(text)

    assert "Bilgi için: [KİŞİ ADI]" in anonymized
    assert "[KURUM ADRESİ]" in anonymized
    assert "[KURUM İLETİŞİM BİLGİLERİ]" in anonymized
    assert "Mahalle muhtarlarına ödenek" in anonymized


def test_ocr_joined_phone_fax_and_kep_footer_becomes_one_placeholder():
    text = (
        "Telefon No: 4491367 Faks No: 4491341 Burak BİLGİCİ\n"
        "KEP Adresi: kurum@example.kep.tr Telefon No: 4491367"
    )

    anonymized = prepare.semantic_anonymize(text)

    assert anonymized == "[KURUM İLETİŞİM BİLGİLERİ]"
    assert "Burak" not in anonymized


def test_honorific_and_extended_signature_title_person_names_are_masked():
    text = (
        "İstanbul Milletvekili Sayın Fethi AÇIKEL tarafından sunulmuştur.\n\n"
        "Cevdet YILMAZ\nCumhurbaşkanı Yardımcısı"
    )

    anonymized = prepare.semantic_anonymize(text)

    assert "Sayın [KİŞİ ADI] tarafından" in anonymized
    assert "[İMZA SAHİBİ]\nCumhurbaşkanı Yardımcısı" in anonymized
    assert "Fethi" not in anonymized
    assert "Cevdet" not in anonymized


def test_petition_article_cleaner_removes_site_chrome_and_comment_tail():
    text = """---
id: DILEKCE-1
---
# Abonelik İptali
Anasayfa
ANASAYFA
Abonelik İptali
Dilekceornegi
7 yıl önce
2 dakikada okunabilir
Facebook'ta Paylaş
Aboneliğin iptali için kuruma yazılı başvuru yapılır.
Bir Cevap Yaz
abonelik iptali seo etiketi
"""

    cleaned = prepare.clean_petition_article(text, "Abonelik İptali")

    assert cleaned.startswith("# Abonelik İptali")
    assert "yıl önce" not in cleaned
    assert "Facebook" not in cleaned
    assert "Bir Cevap Yaz" not in cleaned
    assert "seo etiketi" not in cleaned
    assert "yazılı başvuru" in cleaned


def test_html_extractor_uses_the_official_content_container():
    html = """
    <html><body><nav>Menü</nav><h1 class="dark">Planlı Kesinti</h1>
    <div class="text-content"><p>Sistem 12.00 ile 13.00 arasında kapalı olacaktır.</p>
    <ul><li>Kullanıcılara duyurulur.</li></ul></div><footer>Alt menü</footer></body></html>
    """.encode()

    body, title = prepare.html_to_markdown(html)

    assert title == "Planlı Kesinti"
    assert "kapalı olacaktır" in body
    assert "- Kullanıcılara duyurulur." in body
    assert "Menü" not in body
    assert "Alt menü" not in body


def test_html_extractor_ignores_visually_hidden_institution_heading():
    html = """
    <html><head><meta property="og:title" content="Gerçek Duyuru" /></head><body>
    <h1 class="visually-hidden">T.C. Bakanlık</h1>
    <div class="__header"><h2>Gerçek Duyuru</h2></div>
    <div class="__content"><p>Vatandaşlara yönelik açıklama metni.</p></div>
    </body></html>
    """.encode()

    _body, title = prepare.html_to_markdown(html)

    assert title == "Gerçek Duyuru"


def test_docx_extractor_reads_text_inside_a_floating_text_box():
    document = Document()
    paragraph = document.add_paragraph("Üst bilgi")
    text_box = OxmlElement("w:txbxContent")
    box_paragraph = OxmlElement("w:p")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = "Metin kutusundaki resmî yazışma gövdesi."
    run.append(text)
    box_paragraph.append(run)
    text_box.append(box_paragraph)
    paragraph._p.append(text_box)
    buffer = BytesIO()
    document.save(buffer)

    body = prepare.docx_to_markdown(buffer.getvalue())

    assert "Üst bilgi" in body
    assert "Metin kutusundaki resmî yazışma gövdesi." in body


def test_infer_title_uses_a_short_first_line_for_word_templates():
    assert prepare.infer_title("Tutanak Örneği;\n\nUzun gövde.", "DY-001_tutanak") == "Tutanak Örneği"


def test_quality_gate_separates_atomic_examples_from_reference_documents(tmp_path):
    body = "Resmî yazışma gövdesi. " * 20

    assert prepare.assess_quality(body, source=tmp_path / "ornek.pdf") == ("candidate", "")
    assert prepare.assess_quality("çok kısa", source=tmp_path / "ornek.pdf") == (
        "rejected",
        "yetersiz_metin",
    )
    assert prepare.assess_quality(body, source=tmp_path / "ornek.pdf", page_count=32) == (
        "reference_only",
        "tekil_yazisma_ornegi_degil",
    )


def test_normalizer_repairs_only_question_marks_used_as_apostrophes():
    text = "Türkiye?nin açıklaması nedir? Doğu Anadolu?da uygulanır."

    assert prepare.normalize_markdown(text) == (
        "Türkiye'nin açıklaması nedir? Doğu Anadolu'da uygulanır."
    )


def test_quality_gate_rejects_mojibake_and_corrupted_titles(tmp_path):
    body = "Resmî yazışma gövdesi. " * 20

    assert prepare.assess_quality(
        body + "\nDoğrulama Adresi: Âhüps/example",
        source=tmp_path / "ornek.pdf",
        title="Geçerli başlık",
    ) == ("rejected", "ocr_karakter_bozulmasi")
    assert prepare.assess_quality(
        body,
        source=tmp_path / "ornek.pdf",
        title=", Â Sayı: E-12007 03-1$23865",
    ) == ("rejected", "ocr_karakter_bozulmasi")


def test_front_matter_completion_adds_every_required_field(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    card = repo_root / "datasets" / "resmi_yazisma" / "01_ust_yazi" / "05_teklif" / "UY-1.md"
    monkeypatch.setattr(prepare, "REPO_ROOT", repo_root)

    completed = prepare.complete_front_matter(
        {
            "id": "UY-1",
            "kategori": "ust_yazi",
            "niyet": "05_teklif",
        },
        "# Proje Teklifi\n\nGövde.",
        card,
    )

    assert {
        "id",
        "kategori",
        "alt_kategori",
        "baslik",
        "kaynak",
        "dogrulama",
    } <= completed.keys()
    assert completed["alt_kategori"] == "05_teklif"
    assert completed["baslik"] == "Proje Teklifi"


def test_os_coherence_gate_rejects_the_reported_budget_health_mismatch():
    body = (
        "İl Umumi Hıfzıssıhha Kurulu, Vali başkanlığında toplanmıştır. "
        "İl genelinde halk sağlığını tehdit eden unsurlara karşı denetimler artırılacaktır."
    )

    assert prepare.os_is_coherent("Bütçe Ödeneği Aktarımı Hakkında", body) == (
        False,
        "hifzissihha",
    )
    assert prepare.os_is_coherent("Halk Sağlığı Denetimleri Hakkında", body) == (
        True,
        "hifzissihha",
    )


def test_existing_same_stem_card_is_preferred_over_creating_a_second_card(tmp_path):
    source = tmp_path / "00_gelen_kaynaklar" / "BM-001_duyuru.html"
    companion = tmp_path / "03_bilgilendirme_metni" / "03_uyari" / "BM-001_duyuru.md"
    index = {source.stem.casefold(): [companion]}

    assert prepare.target_for_source(source, index) == companion


def test_source_without_catalog_card_gets_an_adjacent_markdown_file(tmp_path):
    source = tmp_path / "pdf" / "MEB_SIMULASYON_001.pdf"

    assert prepare.target_for_source(source, {}) == source.with_suffix(".md")
