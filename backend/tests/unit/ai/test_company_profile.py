"""Unit tests for the pure, I/O-free half of the company identity layer
(#214): the CompanyProfile dataclass and its prompt rendering."""

from app.ai.identity.company_profile import CompanyProfile
from app.ai.identity.injection import (
    format_agent_identity,
    format_identity_brief_section,
    format_user_address,
)


def test_empty_profile_identity_matches_the_pre_feature_hardcoded_sentence():
    """A company with nothing configured must see byte-identical assistant
    behaviour to before {{agent_identity}} existed."""
    profile = CompanyProfile.empty("company-1")
    assert profile.is_empty
    text = format_agent_identity(profile)
    assert "KACHOW Evrak Karar Destek Sistemi (EKDS)" in text
    assert text.startswith("Sen, **KACHOW Evrak Karar Destek Sistemi (EKDS)**")


def test_empty_profile_brief_section_renders_to_nothing():
    """Same "no empty header" rule as format_adapter_block."""
    profile = CompanyProfile.empty("company-1")
    assert format_identity_brief_section(profile) == ""


def test_configured_profile_identity_uses_company_and_agent_name():
    profile = CompanyProfile(
        company_id="company-1",
        display_name="Ankara Fen İşleri Dairesi Başkanlığı",
        agent_name="Fen İşleri Karar Destek Asistanı",
    )
    text = format_agent_identity(profile)
    assert "Ankara Fen İşleri Dairesi Başkanlığı" in text
    assert "Fen İşleri Karar Destek Asistanı" in text
    assert "KACHOW Evrak Karar Destek Sistemi (EKDS)" not in text


def test_configured_profile_falls_back_to_default_agent_name_when_unset():
    profile = CompanyProfile(company_id="company-1", display_name="Acme A.Ş.")
    text = format_agent_identity(profile)
    assert "Acme A.Ş." in text
    assert "KACHOW Karar Destek Sistemi Asistanı" in text


def test_brief_section_renders_letterhead_and_signer_title():
    profile = CompanyProfile(
        company_id="company-1",
        display_name="Acme A.Ş.",
        letterhead="T.C.\nACME A.Ş.\nFen İşleri Dairesi Başkanlığı",
        default_signer_title="Daire Başkanı",
    )
    section = format_identity_brief_section(profile)
    assert "KURUM KİMLİĞİ" in section
    assert "Acme A.Ş." in section
    assert "Daire Başkanı" in section
    assert "Yazım Briefi" in section


def test_user_address_names_the_caller_when_known():
    text = format_user_address("Ahmet Yılmaz")
    assert "Ahmet Yılmaz" in text


def test_user_address_falls_back_to_a_neutral_instruction_when_unknown():
    text = format_user_address(None)
    assert "bilinmiyor" in text
    assert text != ""


def test_to_dict_excludes_company_id_and_from_dict_round_trips():
    profile = CompanyProfile(
        company_id="company-1",
        version=2,
        display_name="Acme A.Ş.",
        short_name="Acme",
        agent_name="Acme Asistanı",
        letterhead="T.C.\nACME A.Ş.",
        default_signer_title="Genel Müdür",
        updated_at="2026-08-18T00:00:00+00:00",
    )
    payload = profile.to_dict()
    assert "company_id" not in payload

    restored = CompanyProfile.from_dict("company-1", payload)
    assert restored == profile


def test_from_dict_with_none_returns_an_empty_profile_not_an_exception():
    profile = CompanyProfile.from_dict("company-1", None)
    assert profile == CompanyProfile.empty("company-1")


def test_from_dict_tolerates_a_partial_legacy_shaped_value():
    profile = CompanyProfile.from_dict("company-1", {"display_name": "Acme A.Ş."})
    assert profile.display_name == "Acme A.Ş."
    assert profile.agent_name == ""
    assert profile.version == 0
