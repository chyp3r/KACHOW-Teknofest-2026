"""Unit tests for `app.ai.tools.transfer_tools.build_transfer_tools` -- the
`propose_transfer` tool the assist step's model may call (Faz 4, #201).

`FakeTransferProvider` is a tiny in-memory mirror of `TransferGraphProvider`,
just enough to drive every branch the handler can take without a database --
the real `TransferIntentService`/`ArtifactResolutionService` have their own
dedicated unit tests.
"""

import pytest

from app.ai.tools.transfer_tools import build_transfer_tools
from app.domains.transfers.provider import ArtifactResolutionSnapshot, DraftCandidate, IntentSnapshot


class FakeTransferProvider:
    def __init__(
        self,
        *,
        draft_candidates=(),
        recipient_status="resolved",
        recipient_candidates=(),
        policy_permit=True,
    ):
        self.draft_candidates = draft_candidates
        self.recipient_status = recipient_status
        self.recipient_candidates = recipient_candidates
        self.policy_permit = policy_permit
        self.open_intent_calls: list = []
        self._next_id = 0

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
        self.open_intent_calls.append(kwargs)
        resolved_recipient_id = kwargs.get("resolved_recipient_id")
        candidate_recipients = kwargs.get("candidate_recipients") or ()
        if resolved_recipient_id:
            state = "AWAITING_CONFIRMATION" if self.policy_permit else "POLICY_DENIED"
        else:
            state = "AMBIGUOUS"
        return IntentSnapshot(
            id=intent_id,
            state=state,
            artifact_kind=kwargs["artifact_kind"],
            source_artifact_id=kwargs["source_artifact_id"],
            source_version=kwargs.get("source_version"),
            resolved_recipient_id=resolved_recipient_id,
            candidate_recipients=list(candidate_recipients) or None,
            cross_unit=False,
            policy_snapshot=self._policy_snapshot(),
            expires_at=None,
        )


def _draft(id="draft-1", version=1):
    return DraftCandidate(id=id, correspondence_type="cover_letter", version=version, updated_at="")


@pytest.fixture
def proposals():
    seen = []
    return seen


def _build(provider, proposals, **overrides):
    kwargs = dict(
        company_id="company-1",
        user_id="user-1",
        thread_id="thread-1",
        run_id="run-1",
        active_draft_id=None,
        active_document_id=None,
        transfer_provider=provider,
        on_transfer_proposed=proposals.append,
    )
    kwargs.update(overrides)
    tools = build_transfer_tools(**kwargs)
    assert len(tools) == 1
    return tools[0]


def test_no_provider_offers_no_tool(proposals):
    tools = build_transfer_tools(
        company_id="company-1", user_id="user-1", thread_id="t", run_id=None,
        active_draft_id=None, active_document_id=None,
        transfer_provider=None, on_transfer_proposed=proposals.append,
    )
    assert tools == []


def test_missing_caller_identity_offers_no_tool(proposals):
    provider = FakeTransferProvider()
    tools = build_transfer_tools(
        company_id=None, user_id="user-1", thread_id="t", run_id=None,
        active_draft_id=None, active_document_id=None,
        transfer_provider=provider, on_transfer_proposed=proposals.append,
    )
    assert tools == []


@pytest.mark.asyncio
async def test_resolved_recipient_opens_an_intent_and_proposes(proposals):
    provider = FakeTransferProvider(
        draft_candidates=(_draft(version=2),),
        recipient_status="resolved",
        recipient_candidates=[
            type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": "İK"})()
        ],
    )
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet")

    assert "onay" in reply.lower() or "hazır" in reply.lower()
    assert len(proposals) == 1
    assert proposals[0]["outcome"] == "needs_confirmation"
    assert proposals[0]["source_artifact_id"] == "draft-1"
    assert proposals[0]["source_version"] == 2
    assert provider.open_intent_calls[0]["resolved_recipient_id"] == "u-2"


@pytest.mark.asyncio
async def test_ambiguous_recipient_opens_a_disambiguation_intent(proposals):
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="ambiguous",
        recipient_candidates=[
            type("C", (), {"user_id": "u-2", "username": "ahmet-a", "unit_name": "İK"})(),
            type("C", (), {"user_id": "u-3", "username": "ahmet-b", "unit_name": "Hukuk"})(),
        ],
    )
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet")

    assert len(proposals) == 1
    assert proposals[0]["outcome"] == "needs_disambiguation"
    assert len(proposals[0]["candidate_recipients"]) == 2
    assert "onay" in reply.lower() or "seç" in reply.lower()


@pytest.mark.asyncio
async def test_unresolved_draft_never_opens_an_intent(proposals):
    provider = FakeTransferProvider(draft_candidates=())
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet")

    assert "bulamadım" in reply
    assert proposals == []
    assert provider.open_intent_calls == []


@pytest.mark.asyncio
async def test_ambiguous_draft_never_opens_an_intent(proposals):
    provider = FakeTransferProvider(draft_candidates=(_draft(id="d1"), _draft(id="d2")))
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet")

    assert "birden fazla" in reply.lower()
    assert proposals == []


@pytest.mark.asyncio
async def test_recipient_not_found_never_opens_an_intent(proposals):
    provider = FakeTransferProvider(draft_candidates=(_draft(),), recipient_status="not_found")
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="kimse-yok")

    assert "kimse-yok" in reply
    assert proposals == []
    assert provider.open_intent_calls == []


@pytest.mark.asyncio
async def test_policy_denial_never_gates_only_replies(proposals):
    provider = FakeTransferProvider(
        draft_candidates=(_draft(),),
        recipient_status="resolved",
        recipient_candidates=[type("C", (), {"user_id": "u-2", "username": "ahmet", "unit_name": None})()],
        policy_permit=False,
    )
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet")

    assert "favorilerinize" in reply
    assert proposals == []


@pytest.mark.asyncio
async def test_document_kind_resolves_via_resolve_document(proposals):
    provider = FakeTransferProvider()
    tool = _build(provider, proposals)

    reply = await tool.handler(recipient_name="ahmet", artifact_kind="document")

    assert "evrak" in reply.lower()
    assert proposals == []
