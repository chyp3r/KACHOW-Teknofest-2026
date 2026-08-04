"""Tests for page-level document addressing (PageMap + outline)."""

from app.ai.documents.anchors import build_page_map, format_anchor
from app.ai.documents.outline import build_outline, format_outline


def test_page_map_resolves_an_offset_on_the_first_page():
    page_map = build_page_map(["birinci sayfa", "ikinci sayfa"])
    assert page_map.page_for_offset(0) == 1
    assert page_map.page_for_offset(len("birinci sayfa") - 1) == 1


def test_page_map_resolves_an_offset_on_a_later_page():
    pages = ["birinci sayfa", "ikinci sayfa", "üçüncü sayfa"]
    page_map = build_page_map(pages)
    joined = "\n\n".join(pages)

    third_page_offset = joined.index("üçüncü")
    assert page_map.page_for_offset(third_page_offset) == 3


def test_page_map_defaults_to_page_one_with_no_pages():
    page_map = build_page_map([])
    assert page_map.page_for_offset(0) == 1
    assert page_map.page_for_offset(500) == 1


def test_page_map_clamps_an_offset_past_the_end_to_the_last_page():
    page_map = build_page_map(["a", "b"])
    assert page_map.page_for_offset(10_000) == 2


def test_format_anchor_renders_a_citation():
    assert format_anchor(3) == "[s. 3]"


def test_build_outline_previews_the_first_non_blank_line_of_each_page():
    outline = build_outline(["\n\nSayı: 2026/1\nDevamı...", "İkinci sayfa başlığı"])
    assert outline[0].page == 1
    assert outline[0].preview == "Sayı: 2026/1"
    assert outline[1].page == 2
    assert outline[1].preview == "İkinci sayfa başlığı"


def test_build_outline_truncates_a_long_preview():
    long_line = "a" * 200
    outline = build_outline([long_line], preview_chars=10)
    assert outline[0].preview == "a" * 10


def test_format_outline_renders_one_line_per_page():
    outline = build_outline(["birinci", "ikinci"])
    rendered = format_outline(outline)
    assert rendered == "s.1: birinci\ns.2: ikinci"


def test_format_outline_handles_no_pages():
    assert format_outline([]) == "Bu belge için sayfa bilgisi bulunmuyor."
