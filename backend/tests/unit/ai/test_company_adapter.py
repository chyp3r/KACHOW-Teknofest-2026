"""Unit tests for the pure, I/O-free half of the runtime adapter layer
(Faz C2): the CompanyAdapter dataclass and its prompt rendering."""

from app.ai.adapters import CompanyAdapter, format_adapter_block


def test_empty_adapter_renders_to_nothing():
    """A header with nothing under it would read to the model as a
    missing-context signal, not as "no preferences configured" -- see
    _format_style_examples's own docstring for the same rule."""
    adapter = CompanyAdapter.empty("company-1")
    assert adapter.is_empty
    assert format_adapter_block(adapter) == ""


def test_style_rules_render_as_a_bullet_list():
    adapter = CompanyAdapter(
        company_id="company-1",
        style_rules=("Kapanışta her zaman 'Arz ederim' kullan.", "Kısa paragraflar kullan."),
    )
    block = format_adapter_block(adapter)
    assert "- Kapanışta her zaman 'Arz ederim' kullan." in block
    assert "- Kısa paragraflar kullan." in block


def test_avoided_patterns_get_their_own_section():
    adapter = CompanyAdapter(company_id="company-1", avoided_patterns=("Edilgen çatı kullanma.",))
    block = format_adapter_block(adapter)
    assert "Kaçınılacak kalıplar" in block
    assert "Edilgen çatı kullanma." in block


def test_preferred_examples_carry_the_same_never_a_fact_source_boundary_as_style_examples():
    adapter = CompanyAdapter(
        company_id="company-1", preferred_examples=("Örnek yazı metni burada yer alır.",)
    )
    block = format_adapter_block(adapter)
    assert "Örnek yazı metni burada yer alır." in block
    assert "bilgi kaynağı DEĞİLDİR" in block


def test_block_never_asserts_a_fact_only_style_or_format():
    """The class-level boundary note must always be present whenever the
    block renders anything at all -- the one place a leaked adapter could
    otherwise be excused as "the system told me to.\""""
    adapter = CompanyAdapter(company_id="company-1", style_rules=("Bir kural.",))
    block = format_adapter_block(adapter)
    assert "gerekçe olamaz" in block


def test_to_dict_excludes_company_id_and_from_dict_round_trips():
    adapter = CompanyAdapter(
        company_id="company-1",
        version=3,
        style_rules=("Kural.",),
        preferred_examples=("Örnek.",),
        avoided_patterns=("Kaçın.",),
        trained_at="2026-08-15T00:00:00+00:00",
        sample_count=52,
    )
    payload = adapter.to_dict()
    assert "company_id" not in payload

    restored = CompanyAdapter.from_dict("company-1", payload)
    assert restored == adapter


def test_from_dict_with_none_returns_an_empty_adapter_not_an_exception():
    adapter = CompanyAdapter.from_dict("company-1", None)
    assert adapter == CompanyAdapter.empty("company-1")


def test_from_dict_tolerates_a_partial_legacy_shaped_value():
    """A settings blob written by an earlier, smaller version of this
    schema (or hand-edited) must not crash the whole draft turn."""
    adapter = CompanyAdapter.from_dict("company-1", {"style_rules": ["Tek kural."]})
    assert adapter.style_rules == ("Tek kural.",)
    assert adapter.version == 0
    assert adapter.sample_count == 0
