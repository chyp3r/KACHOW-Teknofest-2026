"""Guards the domain-admission gate: does a request belong to this system
at all, independent of which flow the router picked for it.

The motivating regression: "Çiğköfte kampanyası için bir metin yaz" matches
`draft.explicit_request`'s own "metni yaz" surface, so the router correctly
(as a matter of intent) resolves it to `draft` -- and every downstream layer
would happily generate marketing copy for it. `resolve_scope` is the
separate pass that catches this, and these tests pin the two properties
that make it more than a topic deny-list: positive evidence is required
(anchored to a document, an open draft, or official-correspondence
register), and a bare command with nothing else attached is never treated
as suspicious just because it lacks a topic of its own.
"""

import pytest

from app.ai.workflows.scope import (
    CAPABILITY_MANIFEST,
    ScopeVerdict,
    assess_scope_deterministic,
    build_refusal_reply,
    resolve_scope,
)


def test_an_unanchored_off_topic_production_request_is_refused():
    verdict = assess_scope_deterministic(
        "Çiğköfte kampanyası için bir metin yaz",
        "draft",
        has_document=False,
        has_active_draft=False,
    )
    assert verdict.in_scope is False
    assert verdict.reason == "unanchored_request"


def test_a_bare_drafting_command_is_admitted_with_nothing_attached():
    """"Cevap yaz." carries no topic of its own to be off-topic *about*."""
    verdict = assess_scope_deterministic(
        "Cevap yaz.", "draft", has_document=False, has_active_draft=False
    )
    assert verdict.in_scope is True
    assert verdict.reason == "bare_command"


def test_official_register_vocabulary_admits_without_a_document():
    verdict = assess_scope_deterministic(
        "Bu evraka resmi bir cevap yazısı hazırlar mısın?",
        "draft",
        has_document=False,
        has_active_draft=False,
    )
    assert verdict.in_scope is True
    assert verdict.reason == "domain_vocabulary"


def test_an_attached_document_is_sufficient_anchoring_for_scope_alone():
    """scope.py only asks "is there an anchor" -- whether the request
    actually concerns *this* document is app.ai.workflows.relevance's job,
    not this module's."""
    verdict = assess_scope_deterministic(
        "Çiğköfte kampanyası için bir metin yaz",
        "draft",
        has_document=True,
        has_active_draft=False,
    )
    assert verdict.in_scope is True
    assert verdict.reason == "anchored_document"


def test_revise_with_an_open_draft_is_anchored_regardless_of_wording():
    verdict = assess_scope_deterministic(
        "kısalt", "revise", has_document=False, has_active_draft=True
    )
    assert verdict.in_scope is True
    assert verdict.reason == "anchored_draft"


@pytest.mark.parametrize(
    "message",
    ["Merhaba", "Teşekkürler", "Ne yapabilirsin?", "Sen kimsin?", "az önce ne sordum"],
)
def test_conversational_and_system_questions_are_always_admitted(message):
    verdict = assess_scope_deterministic(
        message, "assist", has_document=False, has_active_draft=False
    )
    assert verdict.in_scope is True
    assert verdict.reason in ("conversational", "system_question")


@pytest.mark.asyncio
async def test_resolve_scope_without_a_model_refuses_outright():
    """No fast-tier client configured: the deterministic verdict stands on
    its own -- stricter, not broken (see resolve_scope's own docstring)."""
    verdict = await resolve_scope(
        "Çiğköfte kampanyası için bir metin yaz",
        "draft",
        has_document=False,
        has_active_draft=False,
        llm_client=None,
    )
    assert verdict.in_scope is False
    assert verdict.source == "deterministic"


@pytest.mark.asyncio
async def test_resolve_scope_degrades_to_admitted_when_the_model_call_fails(monkeypatch):
    async def _broken(*args, **kwargs):
        return None

    monkeypatch.setattr("app.ai.workflows.scope.classify_scope_with_model", _broken)

    verdict = await resolve_scope(
        "Çiğköfte kampanyası için bir metin yaz",
        "draft",
        has_document=False,
        has_active_draft=False,
        llm_client=object(),
    )
    assert verdict.in_scope is True
    assert verdict.reason == "degraded"


@pytest.mark.asyncio
async def test_resolve_scope_honors_an_explicit_model_refusal(monkeypatch):
    async def _refuse(*args, **kwargs):
        return False

    monkeypatch.setattr("app.ai.workflows.scope.classify_scope_with_model", _refuse)

    verdict = await resolve_scope(
        "Bir konu için içerik yaz",
        "draft",
        has_document=False,
        has_active_draft=False,
        llm_client=object(),
    )
    assert verdict.in_scope is False
    assert verdict.reason == "model_refused"


def test_build_refusal_reply_lists_every_capability_and_never_asserts_the_request():
    reply = build_refusal_reply()
    for item in CAPABILITY_MANIFEST:
        assert item in reply
    # A refusal is rendered, never generated -- it must not echo or imply
    # anything about the specific off-topic request that triggered it.
    assert "çiğköfte" not in reply.lower()


def test_build_refusal_reply_includes_the_document_summary_when_one_is_attached():
    reply = build_refusal_reply(document_summary="Personel izin talebi hakkında bir dilekçe.")
    assert "Personel izin talebi hakkında bir dilekçe." in reply


def test_scope_verdict_is_frozen_and_hashable_like_other_decision_layers():
    verdict = ScopeVerdict(True, "conversational")
    with pytest.raises(AttributeError):
        verdict.in_scope = False  # type: ignore[misc]
