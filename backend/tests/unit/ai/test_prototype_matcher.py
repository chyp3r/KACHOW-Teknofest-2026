"""Guards the semantic layer's refusal to decide when it shouldn't.

This layer's value is entirely in what it *declines* to do. An embedding matcher
that fires whenever it has a favourite is worse than no matcher: cosine
similarity between short Turkish sentences in the same register is compressed,
so "the closest prototype" is almost always some prototype, and acting on that
would route confidently on noise.

So the tests that matter here are the negative ones -- below either threshold,
with a stale vector file, with a missing file, with the embeddings service down
-- and in every case the required behaviour is the same: return nothing and let
the caller escalate exactly as it did before this layer existed.
"""

import json

import pytest

from app.ai.policy import POLICY_VERSION, get_policy
from app.ai.semantic.prototype_matcher import PrototypeMatcher

MODEL = "test-embed:latest"

#: Two orthogonal unit vectors plus one that sits between them, so similarity
#: and margin are exact rather than approximate.
DRAFT_VECTOR = [1.0, 0.0, 0.0]
ANALYZE_VECTOR = [0.0, 1.0, 0.0]
BETWEEN_VECTOR = [1.0, 1.0, 0.0]


def _write_family(directory, family="intent", *, model=MODEL, policy=POLICY_VERSION):
    payload = {
        "family": family,
        "model": model,
        "dimension": 3,
        "policy_version": policy,
        "prototypes": [
            {"label": "draft", "text": "taslak", "vector": DRAFT_VECTOR},
            {"label": "analyze", "text": "analiz", "vector": ANALYZE_VECTOR},
        ],
    }
    (directory / f"{family}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _matcher(fake_embeddings, directory):
    return PrototypeMatcher(
        fake_embeddings, model_name=MODEL, prototype_dir=directory
    )


@pytest.mark.asyncio
async def test_a_clear_match_is_decisive(fake_embeddings, tmp_path):
    _write_family(tmp_path)
    fake_embeddings.vectors["cevap metni kaleme al"] = DRAFT_VECTOR

    match = await _matcher(fake_embeddings, tmp_path).match(
        "cevap metni kaleme al", "intent"
    )

    assert match is not None
    assert match.label == "draft"
    assert match.decisive is True
    assert match.similarity == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_a_text_equidistant_from_two_labels_is_not_decisive(
    fake_embeddings, tmp_path
):
    """The margin check. Both labels score identically, so there is no winner
    even though one of them is nominally first."""
    _write_family(tmp_path)
    fake_embeddings.vectors["belirsiz istek"] = BETWEEN_VECTOR

    match = await _matcher(fake_embeddings, tmp_path).match("belirsiz istek", "intent")

    assert match is not None
    assert match.decisive is False
    assert match.runner_up_gap == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_a_low_similarity_match_is_not_decisive(fake_embeddings, tmp_path):
    """The absolute check. A clear winner that is still far from every
    prototype is a message this layer has no opinion about."""
    _write_family(tmp_path)
    # Mostly orthogonal to draft, entirely orthogonal to analyze: a clear
    # margin, but a similarity well under the threshold.
    fake_embeddings.vectors["alakasiz"] = [0.3, 0.0, 0.95]

    match = await _matcher(fake_embeddings, tmp_path).match("alakasiz", "intent")

    assert match is not None
    assert match.label == "draft"
    assert match.similarity < get_policy().semantic.decisive_similarity
    assert match.runner_up_gap > get_policy().semantic.decisive_margin
    assert match.decisive is False


@pytest.mark.asyncio
async def test_vectors_built_by_a_different_embedding_model_are_refused(
    fake_embeddings, tmp_path
):
    """Deciding from stale vectors is worse than paying for a model call: it is
    confidently wrong rather than merely slow."""
    _write_family(tmp_path, model="some-other-model")

    matcher = _matcher(fake_embeddings, tmp_path)

    assert matcher.available is False
    assert await matcher.match("herhangi bir mesaj", "intent") is None


@pytest.mark.asyncio
async def test_vectors_built_under_a_different_policy_are_refused(
    fake_embeddings, tmp_path
):
    _write_family(tmp_path, policy="0.0.1")

    assert _matcher(fake_embeddings, tmp_path).available is False


@pytest.mark.asyncio
async def test_a_missing_prototype_directory_disables_the_layer(
    fake_embeddings, tmp_path
):
    """A deployment that never ran build_prototypes.py must degrade, not fail."""
    matcher = _matcher(fake_embeddings, tmp_path / "nope")

    assert matcher.available is False
    assert await matcher.match("mesaj", "intent") is None


@pytest.mark.asyncio
async def test_an_unreadable_prototype_file_is_skipped(fake_embeddings, tmp_path):
    (tmp_path / "intent.json").write_text("{ not json", encoding="utf-8")

    assert _matcher(fake_embeddings, tmp_path).available is False


@pytest.mark.asyncio
async def test_an_embeddings_outage_degrades_to_no_match(fake_embeddings, tmp_path):
    _write_family(tmp_path)
    fake_embeddings.raise_on_query = RuntimeError("ollama is down")

    match = await _matcher(fake_embeddings, tmp_path).match("mesaj", "intent")

    assert match is None


@pytest.mark.asyncio
async def test_an_unknown_family_returns_nothing(fake_embeddings, tmp_path):
    _write_family(tmp_path)

    assert await _matcher(fake_embeddings, tmp_path).match("mesaj", "yok") is None


@pytest.mark.asyncio
async def test_an_empty_message_never_reaches_the_embedding_service(
    fake_embeddings, tmp_path
):
    """The runtime path's only cost is one embed_query; it must not be spent on
    a message with nothing in it."""
    _write_family(tmp_path)

    assert await _matcher(fake_embeddings, tmp_path).match("   ", "intent") is None
    assert fake_embeddings.embed_query_calls == []


@pytest.mark.asyncio
async def test_exactly_one_embedding_call_is_made_per_match(fake_embeddings, tmp_path):
    """No prototype is embedded at request time -- that is the entire reason the
    vectors are precomputed."""
    _write_family(tmp_path)

    await _matcher(fake_embeddings, tmp_path).match("bir mesaj", "intent")

    assert fake_embeddings.embed_query_calls == ["bir mesaj"]
    assert fake_embeddings.embed_documents_calls == []


@pytest.mark.asyncio
async def test_the_best_prototype_per_label_wins_not_the_average(
    fake_embeddings, tmp_path
):
    """A label with one excellent and one poor example must not be penalised for
    the poor one -- prototypes are alternatives, not a centroid."""
    payload = {
        "family": "intent",
        "model": MODEL,
        "dimension": 3,
        "policy_version": POLICY_VERSION,
        "prototypes": [
            {"label": "draft", "text": "iyi", "vector": DRAFT_VECTOR},
            {"label": "draft", "text": "kotu", "vector": [0.0, 0.0, 1.0]},
            {"label": "analyze", "text": "analiz", "vector": ANALYZE_VECTOR},
        ],
    }
    (tmp_path / "intent.json").write_text(json.dumps(payload), encoding="utf-8")
    fake_embeddings.vectors["taslak yaz"] = DRAFT_VECTOR

    match = await _matcher(fake_embeddings, tmp_path).match("taslak yaz", "intent")

    assert match is not None
    assert match.label == "draft"
    assert match.similarity == pytest.approx(1.0)
