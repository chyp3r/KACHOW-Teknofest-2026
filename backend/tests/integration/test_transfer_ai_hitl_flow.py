"""End-to-end interrupt/resume test for the `propose_transfer` tool (Faz 4,
#201).

Same shape as `test_hitl_flow.py`: exercises the real compiled planning
graph -- the assist step's tool loop, `transfer_gate_node`'s `interrupt()`,
checkpointer-backed pause/resume, `transfer_execute` -- with the LLM's own
tool-call *decision* scripted via `fake_llm.generate_with_tools_side_effect`
(see `tests/conftest.py::FakeLLMClient`) rather than left to a real model:
whether the model correctly chooses to call `propose_transfer` for a given
message is a prompt/eval concern (the `evaluation/` harness's territory),
not what this file is proving. What this file proves is that *once the tool
is called*, the rest of the pipeline -- deterministic resolution inside the
tool, the mandatory confirmation gate, execution -- behaves exactly as
designed, the same division `test_hitl_flow.py` already draws by mocking
`draft_graph`/`routing_graph` outright instead of running a real model
through them.

`FakeTransferProvider` is a tiny in-memory mirror of `TransferGraphProvider`
-- see `test_transfer_tools.py`'s own docstring for why a real DB isn't
needed here; `TransferIntentService`/`ArtifactResolutionService` have their
own dedicated unit tests.
"""

from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.ai.llms.base import ToolCallResponse
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings
from app.domains.transfers.provider import ArtifactResolutionSnapshot, DraftCandidate, IntentSnapshot, TransferOutcome


class FakeTransferProvider:
    """In-memory stand-in for `TransferGraphProvider` -- see module docstring."""

    def __init__(
        self,
        *,
        draft_candidates=(),
        recipient_status="resolved",
        recipient_candidates=(),
        policy_permit=True,
        cross_unit=False,
    ):
        self.draft_candidates = draft_candidates
        self.recipient_status = recipient_status
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
        return self.recipient_status, tuple(self.recipient_candidates)

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


def _draft(id="draft-1", version=1):
    return DraftCandidate(id=id, correspondence_type="cover_letter", version=version, updated_at="")


def _scripted_recipient_name(fake_llm, recipient_name: str, *, final_reply: str = "Tamamdır."):
    """Scripts the tool loop: turn 1 calls `propose_transfer`, turn 2
    converges with plain text -- see this module's own docstring for why
    the model's decision is scripted rather than real."""
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(tool_calls=[{"name": "propose_transfer", "args": {"recipient_name": recipient_name}, "id": "1"}]),
        ToolCallResponse(content=final_reply),
    ]


def _build_graph(transfer_provider, fake_llm):
    return create_planning_graph(
        llm_client=fake_llm,
        fast_llm_client=fake_llm,
        document_analysis_graph=MagicMock(),
        rag_graph=MagicMock(),
        draft_graph=MagicMock(),
        routing_graph=MagicMock(),
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
async def test_a_message_naming_nobody_never_calls_the_tool_at_all(fake_llm, fake_fast_llm):
    """No tool_calls scripted at all -- an ordinary conversational turn --
    proves the tool being *offered* never forces the model to use it."""
    monkeypatch_settings = settings.AI_TRANSFER_ENABLED
    settings.AI_TRANSFER_ENABLED = True
    try:
        provider = FakeTransferProvider()
        fake_llm.generate_with_tools_side_effect = [ToolCallResponse(content="Merhaba! Size nasıl yardımcı olabilirim?")]
        graph = _build_graph(provider, fake_llm)
        config = {"configurable": {"thread_id": "transfer-tool-none"}}

        result = await graph.ainvoke(_initial_state("Merhaba"), config=config)

        assert result["final_output"]["status"] == "COMPLETED"
        assert provider.execute_calls == []
        snapshot = await graph.aget_state(config)
        assert not snapshot.next
    finally:
        settings.AI_TRANSFER_ENABLED = monkeypatch_settings


@pytest.mark.asyncio
async def test_resolved_recipient_pauses_for_confirmation_then_executes(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider(
        draft_candidates=(_draft(version=3),),
        recipient_status="resolved",
        recipient_candidates=[type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": "İK"})()],
    )
    _scripted_recipient_name(fake_llm, "ahmet")
    graph = _build_graph(provider, fake_llm)
    config = {"configurable": {"thread_id": "transfer-tool-confirm"}}

    await graph.ainvoke(_initial_state("Son taslağı Ahmet'e gönder"), config=config)

    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    payload = snapshot.tasks[0].interrupts[0].value
    assert payload["kind"] == "artifact_transfer_confirm"
    assert payload["source_version"] == 3
    assert provider.execute_calls == []

    result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert result["final_output"]["transfer"]["transfer_id"] == "transfer-intent-1"
    assert provider.execute_calls == ["intent-1"]
    final_snapshot = await graph.aget_state(config)
    assert not final_snapshot.next


@pytest.mark.asyncio
async def test_ambiguous_recipient_disambiguates_then_confirms(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="ambiguous",
        recipient_candidates=[
            type("C", (), {"user_id": "u-2", "username": "ahmet-a", "unit_name": "İK"})(),
            type("C", (), {"user_id": "u-3", "username": "ahmet-b", "unit_name": "Hukuk"})(),
        ],
    )
    _scripted_recipient_name(fake_llm, "ahmet")
    graph = _build_graph(provider, fake_llm)
    config = {"configurable": {"thread_id": "transfer-tool-disambiguate"}}

    await graph.ainvoke(_initial_state("Taslağı Ahmet'e gönder"), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    assert snapshot.tasks[0].interrupts[0].value["kind"] == "artifact_transfer_disambiguate"

    await graph.ainvoke(Command(resume={"action": "select", "recipient_id": "u-2"}), config=config)
    snapshot = await graph.aget_state(config)
    assert snapshot.next == ("transfer_gate",)
    assert snapshot.tasks[0].interrupts[0].value["kind"] == "artifact_transfer_confirm"

    result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == ["intent-1"]


@pytest.mark.asyncio
async def test_rejecting_confirmation_never_executes(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="resolved",
        recipient_candidates=[type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": None})()],
    )
    _scripted_recipient_name(fake_llm, "ahmet")
    graph = _build_graph(provider, fake_llm)
    config = {"configurable": {"thread_id": "transfer-tool-reject"}}

    await graph.ainvoke(_initial_state("Taslağı Ahmet'e gönder"), config=config)
    result = await graph.ainvoke(Command(resume={"action": "reject"}), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == []
    assert provider.cancel_calls == ["intent-1"]


@pytest.mark.asyncio
async def test_policy_denial_never_opens_a_gate(fake_llm, monkeypatch):
    """The tool's own handler already replied with the denial reason --
    nothing pending, so the turn never pauses at all."""
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="resolved",
        recipient_candidates=[type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": None})()],
        policy_permit=False,
    )
    _scripted_recipient_name(fake_llm, "ahmet", final_reply="Önce favorilerinize ekleyin.")
    graph = _build_graph(provider, fake_llm)
    config = {"configurable": {"thread_id": "transfer-tool-policy-denied"}}

    result = await graph.ainvoke(_initial_state("Taslağı Ahmet'e gönder"), config=config)

    snapshot = await graph.aget_state(config)
    assert not snapshot.next
    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == []


@pytest.mark.asyncio
async def test_without_a_checkpointer_the_proposal_is_cancelled_not_left_pending(fake_llm, monkeypatch):
    """The degrade path every other HITL gate takes: cannot pause for a
    human answer without a checkpointer, so the tool's proposal is
    cancelled outright rather than silently executable."""
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", True)
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="resolved",
        recipient_candidates=[type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": None})()],
    )
    _scripted_recipient_name(fake_llm, "ahmet")
    graph = create_planning_graph(
        llm_client=fake_llm,
        fast_llm_client=fake_llm,
        document_analysis_graph=MagicMock(),
        rag_graph=MagicMock(),
        draft_graph=MagicMock(),
        routing_graph=MagicMock(),
        checkpointer=None,
        transfer_provider=provider,
    )
    config = {"configurable": {"thread_id": "transfer-tool-no-checkpointer"}}

    result = await graph.ainvoke(_initial_state("Taslağı Ahmet'e gönder"), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == []
    assert provider.cancel_calls == ["intent-1"]


@pytest.mark.asyncio
async def test_tool_disabled_by_flag_is_never_offered_to_the_model(fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "AI_TRANSFER_ENABLED", False)
    provider = FakeTransferProvider(draft_candidates=(_draft(),))
    # No tool call scripted -- generate_with_tools should never even see
    # propose_transfer in its `tools` argument to have anything to call.
    fake_llm.generate_with_tools_return = ToolCallResponse(content="Anladım.")
    graph = _build_graph(provider, fake_llm)
    config = {"configurable": {"thread_id": "transfer-tool-flag-off"}}

    result = await graph.ainvoke(_initial_state("Taslağı Ahmet'e gönder"), config=config)

    assert result["final_output"]["status"] == "COMPLETED"
    assert provider.execute_calls == []
    called_tool_names = {
        tool.name for call in fake_llm.generate_with_tools_calls for tool in call["tools"]
    }
    assert "propose_transfer" not in called_tool_names
