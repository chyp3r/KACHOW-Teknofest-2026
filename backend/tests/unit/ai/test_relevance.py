"""Guards the document-relevance gate: does a drafting request actually
concern the document that's attached, not just "is a document attached at
all" (that weaker question is app.ai.workflows.scope's job).

The motivating regression: "Bu evraka çiğköfte kampanyası için bir metin
yaz" has a document attached and clears scope.resolve_scope outright, but
has nothing to do with that document. This module is the narrower check
invoked from planning_graph._step_draft once the document's classification
(and its summary) exists to compare against.
"""

import pytest

from app.ai.workflows.relevance import (
    RelevanceOutput,
    RelevanceVerdict,
    assess_relevance_deterministic,
    build_unrelated_reply,
    resolve_relevance,
)

CLASSIFICATION = {
    "summary": "Personel izin talebi hakkında bir dilekçe. Yıllık izin başvurusu değerlendiriliyor.",
    "document_type_label": "Dilekçe",
}


def test_a_bare_command_is_relevant_with_nothing_further_to_check():
    verdict = assess_relevance_deterministic("Bu evraka cevap yazısı hazırlar mısın?", CLASSIFICATION)
    assert verdict.relevant is True
    assert verdict.reason in ("bare_command", "domain_vocabulary")


def test_an_off_topic_request_against_an_unrelated_document_is_refused():
    verdict = assess_relevance_deterministic(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION
    )
    assert verdict.relevant is False
    assert verdict.reason == "unrelated"


def test_a_request_naming_the_documents_own_subject_is_relevant():
    verdict = assess_relevance_deterministic(
        "İzin talebini onaylayan bir yazı hazırla", CLASSIFICATION
    )
    assert verdict.relevant is True


def test_a_request_overlapping_only_the_documents_summary_wording_is_relevant():
    classification = {"summary": "TOGA yazılım projesi gecikme bildirimi.", "document_type_label": "Bildirim"}
    verdict = assess_relevance_deterministic(
        "TOGA projesiyle ilgili gecikme nedenini açıklayan yazı hazırla", classification
    )
    assert verdict.relevant is True
    assert verdict.reason == "document_overlap"


def test_a_request_explicitly_pointing_at_the_document_is_relevant_regardless_of_vocabulary():
    """The CV false-refusal this guards against: a request naming the
    document's own subject ("bu kişinin") with no vocabulary overlap and no
    DOMAIN_SURFACES hit must still be admitted, not escalated to a model."""
    cv_classification = {
        "summary": "Özgeçmiş belgesi.",
        "document_type_label": "Özgeçmiş",
        "fields": {},
    }
    verdict = assess_relevance_deterministic(
        "Bu kişinin ekibe katılımı ile ilgili bir bilgilendirme metni yaz", cv_classification
    )
    assert verdict.relevant is True
    assert verdict.reason == "deictic_reference"


def test_a_request_naming_a_field_or_entity_not_in_the_summary_is_still_relevant():
    """_document_text now also covers extracted fields/entities, not just
    the summary/type label."""
    classification = {
        "summary": "Bir yazışma.",
        "document_type_label": "Resmî Yazı",
        "fields": {"konu": "Bütçe Artışı Talebi"},
    }
    verdict = assess_relevance_deterministic("Bütçe artışı talebini yanıtlayan bir yazı hazırla", classification)
    assert verdict.relevant is True
    assert verdict.reason == "document_overlap"


def test_an_unambiguous_off_topic_request_still_stays_unrelated():
    """A deictic-looking word alone must not blanket-admit everything --
    only an actual pointer-at-the-document phrase does."""
    verdict = assess_relevance_deterministic(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION
    )
    assert verdict.relevant is False
    assert verdict.reason == "unrelated"


@pytest.mark.asyncio
async def test_resolve_relevance_without_a_model_refuses_outright():
    verdict = await resolve_relevance(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION, llm_client=None
    )
    assert verdict.relevant is False
    assert verdict.source == "deterministic"


@pytest.mark.asyncio
async def test_resolve_relevance_degrades_to_relevant_when_the_model_call_fails(monkeypatch):
    async def _broken(*args, **kwargs):
        return None

    monkeypatch.setattr("app.ai.workflows.relevance.classify_relevance_with_model", _broken)

    verdict = await resolve_relevance(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION, llm_client=object()
    )
    assert verdict.relevant is True
    assert verdict.reason == "degraded"


@pytest.mark.asyncio
async def test_a_low_confidence_model_rejection_is_admitted_not_refused(monkeypatch):
    async def _unsure(*args, **kwargs):
        return RelevanceOutput(relevant=False, confidence=0.4)

    monkeypatch.setattr("app.ai.workflows.relevance.classify_relevance_with_model", _unsure)

    verdict = await resolve_relevance(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION, llm_client=object()
    )
    assert verdict.relevant is True
    assert verdict.reason == "model_relevant"


@pytest.mark.asyncio
async def test_a_high_confidence_model_rejection_is_still_refused(monkeypatch):
    async def _sure(*args, **kwargs):
        return RelevanceOutput(relevant=False, confidence=0.95)

    monkeypatch.setattr("app.ai.workflows.relevance.classify_relevance_with_model", _sure)

    verdict = await resolve_relevance(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION, llm_client=object()
    )
    assert verdict.relevant is False
    assert verdict.reason == "model_unrelated"


@pytest.mark.asyncio
async def test_a_relevant_model_verdict_is_admitted_regardless_of_confidence(monkeypatch):
    async def _relevant(*args, **kwargs):
        return RelevanceOutput(relevant=True, confidence=0.3)

    monkeypatch.setattr("app.ai.workflows.relevance.classify_relevance_with_model", _relevant)

    verdict = await resolve_relevance(
        "Çiğköfte kampanyası için bir metin yaz", CLASSIFICATION, llm_client=object()
    )
    assert verdict.relevant is True
    assert verdict.reason == "model_relevant"


def test_build_unrelated_reply_includes_the_document_summary_and_type():
    reply = build_unrelated_reply("Personel izin talebi.", "Dilekçe")
    assert "Personel izin talebi." in reply
    assert "Dilekçe" in reply


def test_relevance_verdict_is_frozen():
    verdict = RelevanceVerdict(True, "bare_command")
    with pytest.raises(AttributeError):
        verdict.relevant = False  # type: ignore[misc]
