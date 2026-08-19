"""Unit tests for the pure, I/O-free half of the company mandatory-rules
layer (#214): the CompanyRuleSet dataclass and its prompt rendering."""

from app.ai.adapters.company_rules import CompanyRule, CompanyRuleSet
from app.ai.adapters.injection import format_rules_block


def test_empty_ruleset_renders_to_nothing():
    ruleset = CompanyRuleSet.empty("company-1")
    assert ruleset.is_empty
    assert format_rules_block(ruleset) == ""


def test_mandatory_rules_render_under_their_own_section():
    ruleset = CompanyRuleSet(
        company_id="company-1",
        rules=(CompanyRule(id="K1", text="Kapanışta her zaman 'Arz ederim' kullan."),),
    )
    block = format_rules_block(ruleset)
    assert "ZORUNLU" in block
    assert "[K1] Kapanışta her zaman 'Arz ederim' kullan." in block


def test_recommended_rules_get_their_own_section():
    ruleset = CompanyRuleSet(
        company_id="company-1",
        rules=(CompanyRule(id="K2", text="Kısa paragraflar tercih et.", severity="onerilen"),),
    )
    block = format_rules_block(ruleset)
    assert "Önerilen" in block
    assert "[K2] Kısa paragraflar tercih et." in block


def test_disabled_rules_are_excluded_from_the_rendered_block():
    ruleset = CompanyRuleSet(
        company_id="company-1",
        rules=(CompanyRule(id="K1", text="Devre dışı kural.", enabled=False),),
    )
    assert ruleset.is_empty
    assert format_rules_block(ruleset) == ""


def test_block_never_asserts_a_fact_only_a_writing_constraint():
    ruleset = CompanyRuleSet(
        company_id="company-1", rules=(CompanyRule(id="K1", text="Bir kural."),)
    )
    block = format_rules_block(ruleset)
    assert "gerekçe olamaz" in block


def test_enabled_rules_property_filters_disabled():
    ruleset = CompanyRuleSet(
        company_id="company-1",
        rules=(
            CompanyRule(id="K1", text="Açık kural."),
            CompanyRule(id="K2", text="Kapalı kural.", enabled=False),
        ),
    )
    assert [rule.id for rule in ruleset.enabled_rules] == ["K1"]


def test_to_dict_excludes_company_id_and_from_dict_round_trips():
    ruleset = CompanyRuleSet(
        company_id="company-1",
        version=3,
        rules=(
            CompanyRule(id="K1", text="Zorunlu kural.", severity="zorunlu", enabled=True),
            CompanyRule(id="K2", text="Önerilen kural.", severity="onerilen", enabled=False),
        ),
        updated_at="2026-08-18T00:00:00+00:00",
    )
    payload = ruleset.to_dict()
    assert "company_id" not in payload

    restored = CompanyRuleSet.from_dict("company-1", payload)
    assert restored == ruleset


def test_from_dict_with_none_returns_an_empty_ruleset_not_an_exception():
    ruleset = CompanyRuleSet.from_dict("company-1", None)
    assert ruleset == CompanyRuleSet.empty("company-1")


def test_from_dict_drops_items_without_text():
    ruleset = CompanyRuleSet.from_dict(
        "company-1",
        {"rules": [{"id": "K1", "text": "Geçerli kural."}, {"id": "K2", "text": ""}]},
    )
    assert len(ruleset.rules) == 1
    assert ruleset.rules[0].id == "K1"
