"""Unit tests for the Qdrant filter_dict -> models.Filter translation.

Range-condition support (Faz 4 -- RBAC): a value dict of range operators
(e.g. {"sensitivity_rank": {"lte": 3}}) restricts a search by an ordered
numeric payload field, alongside the original exact-match convention.
"""

from qdrant_client.http import models

from app.infrastructure.vectorstore.qdrant import _build_qdrant_filter


def test_empty_filter_dict_returns_none():
    assert _build_qdrant_filter(None) is None
    assert _build_qdrant_filter({}) is None


def test_scalar_value_builds_an_exact_match_condition():
    result = _build_qdrant_filter({"storage_path": "uploads/doc.pdf"})

    assert isinstance(result, models.Filter)
    assert len(result.must) == 1
    condition = result.must[0]
    assert condition.key == "storage_path"
    assert condition.match == models.MatchValue(value="uploads/doc.pdf")


def test_range_dict_value_builds_a_range_condition():
    result = _build_qdrant_filter({"sensitivity_rank": {"lte": 3}})

    condition = result.must[0]
    assert condition.key == "sensitivity_rank"
    assert condition.range == models.Range(lte=3)


def test_range_condition_supports_all_four_operators():
    result = _build_qdrant_filter({"sensitivity_rank": {"gte": 1, "lte": 4}})

    condition = result.must[0]
    assert condition.range == models.Range(gte=1, lte=4)


def test_unrecognised_range_keys_are_dropped_not_passed_through():
    """A stray key in the range dict (typo, unexpected input) must not reach
    models.Range and raise -- it's silently excluded rather than crashing a
    request over a malformed filter."""
    result = _build_qdrant_filter({"sensitivity_rank": {"lte": 3, "bogus": 99}})

    condition = result.must[0]
    assert condition.range == models.Range(lte=3)


def test_mixed_scalar_and_range_conditions_combine_with_must():
    result = _build_qdrant_filter(
        {"storage_path": "uploads/doc.pdf", "sensitivity_rank": {"lte": 2}}
    )

    assert len(result.must) == 2
    by_key = {c.key: c for c in result.must}
    assert by_key["storage_path"].match == models.MatchValue(value="uploads/doc.pdf")
    assert by_key["sensitivity_rank"].range == models.Range(lte=2)
