"""End-to-end interrupt/resume test for the `transfer` plan (Faz 4, #201).

Same shape as `test_hitl_flow.py`: exercises the real compiled planning
graph -- the pre-fusion lexical gate, `transfer_resolve`, `transfer_gate`'s
`interrupt()`, checkpointer-backed pause/resume, `transfer_execute` -- with
only the LLM-backed pieces (the sub-graphs, `extract_transfer_slots`) left
to degrade to their documented fallback (empty slots) rather than mocked
out, since a `MagicMock(spec=BaseLLMClient)` client's async methods raise
when awaited, which `extract_transfer_slots` already treats as "the user
didn't name anyone" -- exactly the scenario these tests want anyway (falls
through to `RecipientRecommendationService`, here faked via
`FakeTransferProvider`).

`FakeTransferProvider` stands in for `app.domains.transfers.provider.
TransferGraphProvider` -- a tiny in-memory mirror of the real CAS state
machine, just enough to drive `AMBIGUOUS -> AWAITING_CONFIRMATION ->
CONFIRMED -> TRANSFER_EXECUTED` (and the deny/cancel branches) without a
database. The real state machine itself (`TransferIntentService`) has its
own unit tests; this file is about the *graph* wiring around it: that
`transfer_gate_node`'s `interrupt()` actually pauses the run, that a reject
never reaches `transfer_execute`, and that the turn's `final_output`
reflects what actually happened.
"""

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings
from app.domains.transfers.provider import ArtifactResolutionSnapshot, DraftCandidate, IntentSnapshot, TransferOutcome


class FakeTransferProvider:
    """In-memory stand-in for `TransferGraphProvider` -- see module docstring."""

    def __init__(
        self,
        *,
        draft_candidates=(),
        recipient_candidates=(),
        policy_permit=True,
        cross_unit=False,
    ):
        self.draft_candidates = draft_candidates
        self.recipient_candidates = recipient_candidates
        self.policy_permit = policy_permit
        self.cross_unit = cross_unit
        self._intents: dict = {}
        self._next_id = 0
        self.execute_calls: list = []
        self.cancel_calls: list = []

    def _policy_snapshot(self):
        if self.policy_permit:
            return None
        return {"reason_code": "favorite_required", "message_tr": "Önce favorilerinize ekleyin."}

    async def resolve_draft(self, **_kwargs):
        candidates = tuple(self.draft_candidates)
        status = "unresolved" if not candidates else ("resolved" if len(candidates) == 1 else "ambiguous")
        return ArtifactResolutionSnapshot(status=status, artifact_kind="draft", draft_candidates=candidates)

    async def resolve_document(self, **_kwargs):
        return ArtifactResolutionSnapshot(status="unresolved", artifact_kind="document")

    async def resolve_recipient(self, **_kwargs):
        return "not_found", ()

    async def recommend_recipients(self, **_kwargs):
        return tuple(self.recipient_candidates)

    async def open_intent(self, **kwargs):
        self._next_id += 1
        intent_id = f"intent-{self._next_id}"
        resolved_recipient_id = kwargs.get("resolved_recipient_id")
        candidate_recipients = kwargs.get("candidate_recipients") or ()
        if resolved_recipient_id:
            state = "AWAITING_CONFIRMATION" if self.policy_permit else "POLICY_DENIED"
        elif candidate_recipients:
            state = "AMBIGUOUS"
        else:
            state = "UNRESOLVED"
        record = {
            "state": state,
            "artifact_kind": kwargs["artifact_kind"],
            "source_artifact_id": kwargs["source_artifact_id"],
            "source_version": kwargs.get("source_version"),
            "resolved_recipient_id": resolved_recipient_id,
            "candidate_recipients": list(candidate_recipients) or None,
        }
        self._intents[intent_id] = record
        return self._snapshot(intent_id)

    async def select_recipient(self, *, intent_id, recipient_id, **_kwargs):
        record = self._intents[intent_id]
        record["resolved_recipient_id"] = recipient_id
        record["state"] = "AWAITING_CONFIRMATION" if self.policy_permit else "POLICY_DENIED"
        return self._snapshot(intent_id)

    async def confirm(self, *, intent_id, **_kwargs):
        record = self._intents[intent_id]
        if record["state"] != "AWAITING_CONFIRMATION":
            return IntentSnapshot(id=intent_id, error_reason="stale", error_message="Bu onay isteği artık geçerli değil.")
        record["state"] = "CONFIRMED"
        return self._snapshot(intent_id)

    async def cancel(self, *, intent_id, **_kwargs):
        self.cancel_calls.append(intent_id)
        record = self._intents[intent_id]
        record["state"] = "CANCELLED"
        return self._snapshot(intent_id)

    async def execute(self, *, intent_id, **_kwargs):
        self.execute_calls.append(intent_id)
        record = self._intents[intent_id]
        if record["state"] != "CONFIRMED":
            return TransferOutcome(error_reason="not_confirmed", error_message="Onaylanmamış bir transfer çalıştırılamaz.")
        record["state"] = "TRANSFER_EXECUTED"
        return TransferOutcome(
            id=f"transfer-{intent_id}",
            status="executed",
            artifact_kind=record["artifact_kind"],
            recipient_id=record["resolved_recipient_id"],
            snapshot_ref="draft-copy-1",
            conversation_id="conv-1",
            cross_unit=self.cross_unit,
        )

    def _snapshot(self, intent_id: str) -> IntentSnapshot:
        record = self._intents[intent_id]
        return IntentSnapshot(
            id=intent_id,
            state=record["state"],
            artifact_kind=record["artifact_kind"],
            source_artifact_id=record["source_artifact_id"],
            source_version=record.get("source_version"),
            resolved_recipient_id=record.get("resolved_recipient_id"),
            candidate_recipients=record.get("candidate_recipients"),
            cross_unit=self.cross_unit,
            policy_snapshot=self._policy_snapshot(),
            expires_at=None,
        )


def _build_graph(transfer_provider):
    document_analysis_graph = MagicMock()
    rag_graph = MagicMock()
    draft_graph = MagicMock()
    routing_graph = MagicMock()
    return create_planning_graph(
        llm_client=MagicMock(spec=BaseLLMClient),
        fast_llm_client=MagicMock(spec=BaseLLMClient),
        document_analysis_graph=document_analysis_graph,
        rag_graph=rag_graph,
        draft_graph=draft_graph,
        routing_graph=routing_graph,
        checkpointer=MemorySaver(),
        transfer_provider=transfer_provider,
    )


def _initial_state(message: str) -> dict:
    return {
        "input_text": message,
        "document_id": None,
        "company_id": "company-1",
        "user_id": "user-1",
    }


@pytest.mark.asyncio
async def test_draft_turn_does_not_offer_transfer(monkeypatch):
    """The most important behavioural guarantee in the plan's §C1: drafting
    never ends with an automatic offer to send. A plain drafting message
    must resolve to the `draft` plan, never `transfer`, whether or not the
    flag is on."""
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    from app.ai.workflows.planner import resolve_plan

    decision = await resolve_plan("Bu evraka cevap yazısı hazırla ve gönder", None)
    assert decision.intent == "draft"
    assert "transfer_execute" not in decision.steps


@pytest.mark.asyncio
async def test_transfer_disabled_by_default_falls_through_to_ordinary_ladder():
    from app.ai.workflows.planner import resolve_plan

    decision = await resolve_plan("Taslağı Ahmet'e gönder", None)
    assert decision.intent != "transfer"


@pytest.mark.asyncio
async def test_ambiguous_recipient_pauses_then_confirming_executes(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    from app.domains.transfers.recommendation import RecipientRecommendation

    provider = FakeTransferProvider(
        draft_candidates=(DraftCandidate(id="draft-1", correspondence_type="cover_letter", version=1, updated_at=""),),
        recipient_candidates=(
            RecipientRecommendation(user_id="u-2", username="ahmet", source="unit_member", unit_id="unit-1", unit_name="IK"),
            RecipientRecommendation(user_id="u-3", username="mehmet", source="unit_member", unit_id="unit-1", unit_name="IK"),
        ),
    )
    graph = _build_graph(provider)
    config = {"configurable": {"thread_id": "transfer-ambiguous"}}

    await graph.ainvoke(_initial_state("Son taslağı gönder"), config=config)

    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["kind"] == "artifact_transfer_disambiguate"
    assert len(payload["candidates"]) == 2

    # Pick the first candidate -- immediately re-pauses for confirmation,
    # never executes on a bare selection.
    await graph.ainvoke(
        Command(resume={"action": "select", "recipient_id": "u-2"}), config=config
    )
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    confirm_payload = snapshot.tasks[0].interrupts[0].value
    assert confirm_payload["kind"] == "artifact_transfer_confirm"
    assert provider.execute_calls == []

    result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert result["final_output"]["transfer"]["transfer_id"] == "transfer-intent-1"
    assert provider.execute_calls == ["intent-1"]


@pytest.mark.asyncio
async def test_rejecting_confirmation_never_executes(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    from app.domains.transfers.recommendation import RecipientRecommendation

    provider = FakeTransferProvider(
        draft_candidates=(DraftCandidate(id="draft-1", correspondence_type="cover_letter", version=1, updated_at=""),),
        recipient_candidates=(
            RecipientRecommendation(user_id="u-2", username="ahmet", source="unit_member", unit_id="unit-1", unit_name="IK"),
        ),
    )
    graph = _build_graph(provider)
    config = {"configurable": {"thread_id": "transfer-reject"}}

    await graph.ainvoke(_initial_state("Son taslağı gönder"), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    assert snapshot.tasks[0].interrupts[0].value["kind"] == "artifact_transfer_confirm"

    result = await graph.ainvoke(Command(resume={"action": "reject"}), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == []
    assert provider.cancel_calls == ["intent-1"]


@pytest.mark.asyncio
async def test_policy_denial_ends_the_turn_without_a_gate(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    from app.domains.transfers.recommendation import RecipientRecommendation

    provider = FakeTransferProvider(
        draft_candidates=(DraftCandidate(id="draft-1", correspondence_type="cover_letter", version=1, updated_at=""),),
        recipient_candidates=(
            RecipientRecommendation(user_id="u-2", username="ahmet", source="unit_member", unit_id="unit-1", unit_name="IK"),
        ),
        policy_permit=False,
    )
    graph = _build_graph(provider)
    config = {"configurable": {"thread_id": "transfer-policy-denied"}}

    result = await graph.ainvoke(_initial_state("Son taslağı gönder"), config=config)

    snapshot = await graph.aget_state(config)
    assert not snapshot.next
    assert result["final_output"]["status"] == "COMPLETED"
    assert "favorilerinize" in result["final_output"]["assist"]["reply"]
    assert provider.execute_calls == []


@pytest.mark.asyncio
async def test_no_draft_found_ends_the_turn_without_a_gate(monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider()
    graph = _build_graph(provider)
    config = {"configurable": {"thread_id": "transfer-unresolved"}}

    result = await graph.ainvoke(_initial_state("Son taslağı gönder"), config=config)

    snapshot = await graph.aget_state(config)
    assert not snapshot.next
    assert result["final_output"]["status"] == "COMPLETED"
    assert "bulamadım" in result["final_output"]["assist"]["reply"]
