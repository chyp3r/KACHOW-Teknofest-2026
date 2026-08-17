"""Unit tests for `planner._try_transfer` -- the pre-fusion lexical gate for
the `transfer` plan (Faz 4, #201). See `intent_rules.TRANSFER_VERB_SURFACES`'s
docstring for why this is a standalone, high-precision gate rather than a
fifth label in the calibrated four-way fusion softmax.
"""

import pytest

from app.ai.workflows.planner import PLAN_BY_INTENT, resolve_plan
from app.core.config import settings


@pytest.fixture(autouse=True)
def _enable_transfer(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)


@pytest.mark.asyncio
async def test_verb_plus_artifact_resolves_to_transfer():
    decision = await resolve_plan("Son taslağı Ahmet'e gönder", None)
    assert decision.intent == "transfer"
    assert decision.steps == PLAN_BY_INTENT["transfer"]
    assert decision.source == "transfer_lexical"


@pytest.mark.asyncio
async def test_evrak_ilet_also_resolves_to_transfer():
    decision = await resolve_plan("Bu evrakı Mehmet'e ilet", None)
    assert decision.intent == "transfer"


@pytest.mark.asyncio
async def test_verb_alone_without_artifact_noun_does_not_resolve_to_transfer():
    decision = await resolve_plan("Selam, nasılsın?", None)
    assert decision.intent != "transfer"


@pytest.mark.asyncio
async def test_a_drafting_creation_verb_vetoes_transfer_even_with_gonder(monkeypatch):
    """The plan's §C1 invariant: "taslak hazırla ve gönder" must resolve to
    `draft`, never `transfer` -- nothing exists yet to send, and transfer is
    never an automatic continuation of drafting."""
    decision = await resolve_plan("Taslak hazırla ve gönder", None)
    assert decision.intent != "transfer"


@pytest.mark.asyncio
async def test_disabled_by_default_never_produces_a_transfer_plan(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", False)
    decision = await resolve_plan("Son taslağı Ahmet'e gönder", None)
    assert decision.intent != "transfer"


@pytest.mark.asyncio
async def test_transfer_never_appears_in_a_compound_plan():
    """transfer is deliberately excluded from COMPOUND_PAIR -- a message
    that also reads as draft/analyze must never silently fold a send into
    the same turn."""
    decision = await resolve_plan("Bu evrakı incele, taslak hazırla ve gönder", "uploads/doc.pdf")
    assert "transfer_execute" not in decision.steps
