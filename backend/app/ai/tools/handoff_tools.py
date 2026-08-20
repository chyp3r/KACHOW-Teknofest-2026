"""The request_handoff tool the assistant agent may call for one turn (Faz 7).

``assistant.md``'s own "Üretim Yasağı" rule tells the model to politely
refuse anything outside its five core capabilities -- but "Cevap Taslağı
Hazırlama" (drafting) and revising the active draft *are* two of those five.
A message that should have routed to ``draft``/``revise`` but landed on
``assist`` instead (a weak or fallback routing decision, see
``planning_graph._deterministic_handoff_target`` for the deterministic half
of this fix) has no text-pattern the assistant's own free-form reply
reliably signals -- unlike ``propose_transfer``, there is no fixed shape to
detect after the fact. This tool gives the model an explicit, structured way
to say "this belongs to draft/revise instead of me" rather than writing the
content itself (which would violate Üretim Yasağı in spirit even when it
technically produces a usable letter) or refusing a perfectly legitimate
request outright.

Same one-turn, propose-only shape as ``app.ai.tools.transfer_tools``: the
handler never mutates graph state directly (a tool handler runs inside the
assist step's own node, see that module's docstring on why), it only hands
the request back to ``planning_graph._step_assist`` through a side-channel
callback, which is what actually appends the target flow's own steps to
``plan_steps``.
"""

from typing import Callable, Literal

from pydantic import BaseModel, Field

from app.ai.tools.registry import ToolSpec


class RequestHandoffArgs(BaseModel):
    """Arguments for the ``request_handoff`` tool."""

    target: Literal["draft", "revise"] = Field(
        description=(
            "Bu istek gerçekte hangi akışa ait: 'draft' (yeni bir resmî yazı/taslak "
            "hazırlanması isteniyor) veya 'revise' (mevcut aktif taslakta somut bir "
            "değişiklik isteniyor)."
        )
    )
    reason: str = Field(
        default="",
        description="Bu isteğin neden kendi görev alanın yerine bu akışa ait olduğunun kısa gerekçesi.",
    )


def build_handoff_tools(
    *,
    has_active_draft: bool,
    on_handoff_requested: Callable[[dict], None],
) -> list[ToolSpec]:
    """Build the ``request_handoff`` tool.

    Args:
        has_active_draft: Whether ``SessionFocus.active_draft`` is set this
            turn -- ``target="revise"`` is refused (never handed off) when
            there is nothing to revise, the same guarantee
            ``_step_revise``/``intent_scorer.score_intents`` already give
            the deterministic routing path (C-item: revise is never handed
            off to without an active draft).
        on_handoff_requested: Side-channel callback receiving
            ``{"target": ..., "reason": ...}`` when the model calls this
            tool -- mirrors ``build_transfer_tools``'s
            ``on_transfer_proposed`` exactly.

    Returns:
        A single-tool list.
    """

    async def _request_handoff(target: str, reason: str = "") -> str:
        if target == "revise" and not has_active_draft:
            return (
                "Şu anda revize edilecek aktif bir taslak yok; bu isteğe normal "
                "yanıtını vermeye devam et."
            )
        on_handoff_requested({"target": target, "reason": reason})
        return "İstek ilgili akışa yönlendiriliyor; buna ek bir açıklama üretmene gerek yok."

    return [
        ToolSpec(
            name="request_handoff",
            description=(
                "Kullanıcının mesajı aslında yeni bir resmî yazı/taslak hazırlanmasını "
                "(draft) veya mevcut aktif taslakta somut bir değişiklik yapılmasını "
                "(revise) istiyorsa -- ama bu istek yanlışlıkla sana yönlendirildiyse -- "
                "kendi cevabını üretmeye veya reddetmeye çalışmak yerine bu aracı çağır. "
                "Yalnızca istek gerçekten bu iki akıştan birine aitse çağır; genel bir "
                "soru, sohbet veya sistemin görev alanı dışında kalan bir istek için "
                "ASLA çağırma."
            ),
            args_schema=RequestHandoffArgs,
            handler=_request_handoff,
        )
    ]
