"""The transfer tool the assistant agent may call for one turn (Faz 4, #201).

Unlike every other tool in :mod:`app.ai.tools.document_tools`, calling this
one can lead to a paused, human-confirmed action rather than just returning
text. That pause is deliberately **not** implemented by this tool calling
``interrupt()`` itself: a tool handler runs inside the assist step's own
node (see ``planning_graph._step_assist``/``_run_assist``), and
``interrupt()`` replays its *whole* owning node from the top on resume --
for the assist step that would mean re-running the model's entire streaming
reply and every earlier tool call in the same turn a second time, the exact
cost ``brief_gate``/``human_gate`` were split into their own nodes to avoid
paying (see their own docstrings).

So this tool only ever *proposes*: it resolves the artifact and recipient
deterministically and opens an ``artifact_transfer_intents`` row (via
``TransferIntentService``, reached through ``transfer_provider`` -- this
module is under ``app.ai.*`` and never imports ``app.domains.*`` directly,
same as every other injected-provider call site), then hands the outcome
back to ``_step_assist`` through ``on_transfer_proposed`` -- a side-channel
callback, the same pattern ``on_anchor_referenced``/``on_tool_result``
already use. ``_step_assist`` is what actually routes the turn to
``transfer_gate_node`` (a separate node, safe to interrupt from) for the
mandatory, server-enforced confirmation. The text this handler returns to
the model is purely descriptive -- whatever the model says about it in its
own reply, the transfer only ever executes after a human clicks "Onayla" on
the real confirmation card, and ``TransferIntentService.execute`` refuses
anything not persisted as ``CONFIRMED`` regardless of what any caller (this
tool, the model, the graph) believes happened.
"""

from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec


class ProposeTransferArgs(BaseModel):
    """Arguments for the ``propose_transfer`` tool."""

    recipient_name: str = Field(
        description="Kullanıcının belirttiği alıcının adı veya kullanıcı adı."
    )
    artifact_kind: Optional[Literal["draft", "document"]] = Field(
        default=None,
        description=(
            "Gönderilecek şeyin türü: 'draft' (taslak) veya 'document' (evrak). "
            "Kullanıcı açıkça belirtmemişse null bırak -- en son taslak varsayılan olarak kullanılır."
        ),
    )


#: Terminal outcomes the tool resolves and replies about in plain text --
#: nothing to confirm, so `_step_assist` never routes to `transfer_gate` for
#: these (mirrors `_settle` in the now-removed deterministic `transfer_resolve`
#: step, minus the two outcomes that still need a human: see `_GATED_OUTCOMES`).
_TERMINAL_REPLIES = {
    "unresolved": "Gönderilecek bir {noun} bulamadım.",
    "recipient_not_found": "'{recipient_name}' adında bir kullanıcı bulamadım.",
    "artifact_ambiguous": "Birden fazla {noun} buldum; hangisini kastettiğinizi belirtir misiniz?",
}

#: Outcomes that must pause for a human -- `_step_assist` routes to
#: `transfer_gate_node` for exactly these two, never for anything above.
_GATED_OUTCOMES = {"needs_disambiguation", "needs_confirmation"}


def build_transfer_tools(
    *,
    company_id: Optional[str],
    user_id: Optional[str],
    thread_id: str,
    run_id: Optional[str],
    active_draft_id: Optional[str],
    active_document_id: Optional[str],
    transfer_provider: Any,
    on_transfer_proposed: Callable[[dict], None],
) -> list[ToolSpec]:
    """Build the ``propose_transfer`` tool, when it's actually usable.

    Returns an empty list -- the model is never even offered the tool --
    when ``transfer_provider`` is unset (feature not wired for this
    deployment) or the caller identity is missing (``company_id``/
    ``user_id``, the open demo/dev path with ``REQUIRE_AUTH`` off): a
    transfer with no authenticated sender has nothing to authorize against.
    The ``settings.AI_TRANSFER_ENABLED`` gate itself lives one level up, in
    ``_run_assist`` -- consistent with how every other feature flag in this
    codebase is checked once at the call site, not duplicated into each
    tool/provider it gates.
    """
    if transfer_provider is None or not company_id or not user_id:
        return []

    async def _propose_transfer(recipient_name: str, artifact_kind: Optional[str] = None) -> str:
        kind = artifact_kind if artifact_kind in ("draft", "document") else "draft"
        noun = "taslak" if kind == "draft" else "evrak"

        if kind == "draft":
            resolution = await transfer_provider.resolve_draft(
                company_id=company_id, user_id=user_id, thread_id=thread_id, explicit_draft_id=active_draft_id
            )
        else:
            resolution = await transfer_provider.resolve_document(
                company_id=company_id, user_id=user_id, focus_document_id=active_document_id
            )

        if resolution.status == "unresolved":
            return _TERMINAL_REPLIES["unresolved"].format(noun=noun)
        if resolution.status == "ambiguous":
            candidates = resolution.draft_candidates or resolution.document_candidates
            listing = "; ".join(
                (f"v{c.version} ({c.correspondence_type or 'taslak'})" if kind == "draft" else c.file_name)
                for c in candidates
            )
            return _TERMINAL_REPLIES["artifact_ambiguous"].format(noun=noun) + f" ({listing})"

        artifact = (resolution.draft_candidates or resolution.document_candidates)[0]
        source_artifact_id = artifact.id
        source_version = artifact.version if kind == "draft" else None

        status, candidates = await transfer_provider.resolve_recipient(
            company_id=company_id, name=recipient_name, requester_id=user_id
        )
        if status == "not_found":
            return _TERMINAL_REPLIES["recipient_not_found"].format(recipient_name=recipient_name)

        recipient_candidates = [
            {"user_id": c.user_id, "username": c.username, "unit_name": c.unit_name, "source": "name_match"}
            for c in candidates
        ]
        resolved_recipient_id = recipient_candidates[0]["user_id"] if status == "resolved" else None

        intent = await transfer_provider.open_intent(
            company_id=company_id,
            thread_id=thread_id,
            run_id=run_id,
            requester_id=user_id,
            artifact_kind=kind,
            source_artifact_id=source_artifact_id,
            source_version=source_version,
            resolved_recipient_id=resolved_recipient_id,
            candidate_recipients=tuple(recipient_candidates) if status == "ambiguous" else (),
        )

        if intent.error_reason:
            return intent.error_message or "Transfer başlatılamadı."
        if intent.state == "POLICY_DENIED":
            return (intent.policy_snapshot or {}).get("message_tr") or "Bu transfer şu anda gerçekleştirilemiyor."

        outcome = "needs_confirmation" if intent.state == "AWAITING_CONFIRMATION" else "needs_disambiguation"
        on_transfer_proposed(
            {
                "status": "COMPLETED",
                "outcome": outcome,
                "intent_id": intent.id,
                "artifact_kind": kind,
                "source_artifact_id": source_artifact_id,
                "source_version": source_version,
                "candidate_recipients": intent.candidate_recipients,
                "cross_unit": intent.cross_unit,
                "policy_snapshot": intent.policy_snapshot,
            }
        )
        if outcome == "needs_disambiguation":
            return (
                f"Aynı isimde birden fazla kullanıcı buldum; hangisini kastettiğinizi "
                f"onay ekranından seçebilirsiniz."
            )
        return (
            f"{noun.capitalize()}ı göndermeye hazır -- onayınızı bekliyorum."
        )

    return [
        ToolSpec(
            name="propose_transfer",
            description=(
                "Kullanıcının bir taslağı veya evrakı belirli bir kişiye göndermesini "
                "önerir. Kullanıcı 'şunu ona gönder', 'taslağı Ahmet'le paylaş' gibi "
                "birine bir şey göndermek istediğini açıkça belirttiğinde çağır -- "
                "asla kendiliğinden, taslak üretiminin bir devamı olarak çağırma. "
                "Bu çağrı transferi hemen gerçekleştirmez; kullanıcıya ayrı bir onay "
                "ekranı gösterilir, gönderim yalnızca kullanıcı orada onaylarsa olur."
            ),
            args_schema=ProposeTransferArgs,
            handler=_propose_transfer,
        )
    ]
