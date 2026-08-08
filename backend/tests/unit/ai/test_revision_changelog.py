"""Unit tests for the deterministic, LLM-free revision change log."""

from app.ai.revision.changelog import build_changelog
from app.ai.revision.instruction import decompose_instruction

BEFORE = (
    "Konu: Personel İzin Talebi\n\n"
    "Sayın Makam,\n\n"
    "İlgi yazı kapsamında personelimizin izin talebi tarafımıza iletilmiştir.\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)


def test_an_unchanged_draft_produces_no_entries():
    changelog = build_changelog(BEFORE, BEFORE)
    assert changelog.entries == []
    assert "tespit edilmedi" in changelog.summary


def test_a_single_paragraph_edit_produces_one_entry():
    after = BEFORE.replace("Sayın Makam,", "Sayın Vali Bey,")
    changelog = build_changelog(BEFORE, after)

    assert len(changelog.entries) == 1
    entry = changelog.entries[0]
    assert entry.before == "Sayın Makam,"
    assert entry.after == "Sayın Vali Bey,"
    assert entry.char_delta == len("Sayın Vali Bey,") - len("Sayın Makam,")


def test_an_added_paragraph_has_no_before_text():
    after = BEFORE + "\n\nEk: Bir belge eklenmiştir."
    changelog = build_changelog(BEFORE, after)

    assert len(changelog.entries) == 1
    assert changelog.entries[0].before == ""
    assert changelog.entries[0].after == "Ek: Bir belge eklenmiştir."
    assert "eklendi" in changelog.summary


def test_a_removed_paragraph_has_no_after_text():
    after = BEFORE.replace("\n\nArz ederim.", "")
    changelog = build_changelog(BEFORE, after)

    assert any(entry.after == "" and entry.before == "Arz ederim." for entry in changelog.entries)


def test_directives_are_attributed_positionally_as_a_hint():
    directives = decompose_instruction("Konuyu değiştir ve son paragrafı kısalt.")
    after = BEFORE.replace("Konu: Personel İzin Talebi", "Konu: Yıllık İzin Talebi").replace(
        "Ali Veli\nGenel Müdür", "A.V."
    )
    changelog = build_changelog(BEFORE, after, directives)

    assert len(changelog.entries) == 2
    assert changelog.entries[0].directive == directives[0].raw
    assert changelog.entries[1].directive == directives[1].raw


def test_a_long_snippet_is_truncated():
    long_paragraph = "x" * 1000
    after = BEFORE + f"\n\n{long_paragraph}"
    changelog = build_changelog(BEFORE, after)

    assert len(changelog.entries[0].after) <= 400
    assert changelog.entries[0].after.endswith("…")
