"""Document-relevance admission for the draft flow.

``app.ai.workflows.scope`` answers whether a production request is anchored
to *something* -- a document, an open draft, or the official-correspondence
register. An attached document is treated there as sufficient anchoring on
its own, which is the right call for scope (a document is evidence the turn
is about *some* piece of business), but it is too generous for the draft
step specifically: "Bu evraka çiğköfte kampanyası için bir metin yaz" has a
document attached and would clear ``scope.resolve_scope`` outright, yet the
requested text has nothing to do with that document either.

This module is the second, narrower check that catches exactly that gap.
Where scope asks "is there an anchor at all", this asks "does the request
actually concern *this* anchor" -- and it only ever runs once a document is
attached and its classification (in particular ``summary``) is already
available, which is why it is invoked from inside
``planning_graph._step_draft`` rather than at plan-resolution time the way
scope is: the summary it compares against does not exist until the
classification step has run.

Same two-layer shape as ``scope`` and as ``app.ai.revision.conflict``: a
free deterministic pass settles the overwhelming majority of turns (a bare
"taslak hazırla" carries no topic of its own to be irrelevant *about*; a
request phrased in administrative register or that names something the
document's own summary already mentions is presumptively on-topic), and
only a request that clears neither test is escalated to a fast-tier model
call, with the deterministic verdict standing if no model is configured.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.scope import DOMAIN_SURFACES
from app.ai.workflows.topic_words import content_words

logger = logging.getLogger(__name__)

__all__ = [
    "RelevanceVerdict",
    "assess_relevance_deterministic",
    "build_unrelated_reply",
    "classify_relevance_with_model",
    "resolve_relevance",
]

RelevanceReason = Literal[
    "bare_command",
    "domain_vocabulary",
    "document_overlap",
    "model_relevant",
    "model_unrelated",
    "unrelated",
    "degraded",
]


@dataclass(frozen=True)
class RelevanceVerdict:
    """Whether a drafting instruction actually concerns the attached document.

    Attributes:
        relevant: False only when the draft step should refuse to run.
        reason: Which rule settled it (see ``RelevanceReason``).
        source: ``"deterministic"`` or ``"model"``.
        detail: Turkish audit note, not shown to the user verbatim.
    """

    relevant: bool
    reason: RelevanceReason
    source: Literal["deterministic", "model"] = "deterministic"
    detail: str = ""


class RelevanceOutput(BaseModel):
    """The fast-tier model's verdict on an unanchored-looking draft request."""

    relevant: bool = Field(
        description=(
            "Kullanıcının isteği, verilen belge özetiyle aynı iş/konuyu mu "
            "ele alıyor? Belgeyle konu olarak ilgisizse (tamamen farklı bir "
            "konu -- ör. pazarlama, reklam, genel kültür, kişisel bir metin) "
            "false döndür."
        )
    )


def _document_text(classification: dict[str, Any]) -> str:
    return normalize(
        " ".join(
            part
            for part in (
                classification.get("summary", ""),
                classification.get("document_type_label", ""),
            )
            if part
        )
    )


def assess_relevance_deterministic(
    instruction: str, classification: dict[str, Any]
) -> RelevanceVerdict:
    """Settle relevance from the instruction and the document's own summary.

    Args:
        instruction: The user's raw message this turn (not the composed
            writer prompt -- that already has boilerplate wrapped around it).
        classification: The turn's resolved classification, carrying
            ``summary``/``document_type_label``.

    Returns:
        A verdict. ``relevant=False`` with reason ``"unrelated"`` is the one
        outcome worth escalating to a model (see ``resolve_relevance``);
        every other outcome is final.
    """
    normalized = normalize(instruction)
    words = content_words(instruction)

    if not words:
        return RelevanceVerdict(
            True, "bare_command", detail="İstek belgeden bağımsız bir konu içermiyor."
        )

    padded = f" {normalized} "
    if any(f" {surface}" in padded for surface in DOMAIN_SURFACES):
        return RelevanceVerdict(
            True, "domain_vocabulary", detail="İstek resmî yazışma terminolojisi içeriyor."
        )

    document_text = _document_text(classification)
    if document_text and any(word in document_text for word in words):
        return RelevanceVerdict(
            True, "document_overlap", detail="İstek belgenin kendi içeriğiyle örtüşüyor."
        )

    return RelevanceVerdict(
        False,
        "unrelated",
        detail=(
            "İstekteki konu ne belgenin özetiyle ne de resmî yazışma "
            "terminolojisiyle örtüşüyor."
        ),
    )


async def classify_relevance_with_model(
    llm_client: BaseLLMClient, instruction: str, classification: dict[str, Any]
) -> Optional[bool]:
    """Ask the fast tier whether an unanchored-looking request fits the document.

    Args:
        llm_client: Fast-tier client, the same one the router's own
            tie-breaker and the scope gate use.
        instruction: The user's message.
        classification: The turn's resolved classification.

    Returns:
        The model's verdict, or ``None`` when the call failed -- distinct
        from ``False`` so a provider outage never reads as a refusal.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="RelevanceClassifier",
        description="Decides whether a draft request concerns the attached document.",
        system_prompt=(
            "Sana bir belge özeti ve bir kullanıcı isteği verilecek. İsteğin "
            "bu belgeyle aynı iş/konuyu ele alıp almadığına karar ver. "
            "Yalnızca yapılandırılmış JSON döndür."
        ),
    )

    prompt = (
        f"Belge türü: {classification.get('document_type_label', 'bilinmiyor')}\n"
        f"Belge özeti: {classification.get('summary', '(özet yok)')}\n\n"
        f'Kullanıcı isteği: "{instruction}"\n\n'
        "Bu istek belgeyle aynı konuyu mu ele alıyor?"
    )

    try:
        result: RelevanceOutput = await agent.run_structured(
            messages=prompt,
            response_model=RelevanceOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.relevant
    except Exception:
        logger.warning(
            "Relevance classification failed; falling back to deterministic verdict."
        )
        return None


async def resolve_relevance(
    instruction: str,
    classification: dict[str, Any],
    llm_client: Optional[BaseLLMClient] = None,
) -> RelevanceVerdict:
    """Resolve relevance, escalating only the case a model call can improve.

    Args:
        instruction: The user's message.
        classification: The turn's resolved classification.
        llm_client: Fast-tier client. Omitted means the deterministic verdict
            stands on its own -- stricter, not broken, matching
            ``scope.resolve_scope``'s same no-model behaviour: an
            unrelated-looking request is refused without a model getting a
            chance to admit it.

    Returns:
        The final verdict.
    """
    verdict = assess_relevance_deterministic(instruction, classification)
    if verdict.relevant or llm_client is None:
        return verdict

    admitted = await classify_relevance_with_model(llm_client, instruction, classification)
    if admitted is None:
        # A broken call, not a broken request -- see scope.resolve_scope's
        # identical reasoning for "degraded".
        return RelevanceVerdict(
            True,
            "degraded",
            source="model",
            detail="Konu uygunluk modeli yanıt vermedi; istek kapsam içi sayıldı.",
        )
    if admitted:
        return RelevanceVerdict(
            True, "model_relevant", source="model", detail="Model belgeyle ilgili buldu."
        )
    return RelevanceVerdict(
        False, "model_unrelated", source="model", detail="Model belgeyle ilgisiz buldu."
    )


def build_unrelated_reply(document_summary: str, document_type_label: str = "") -> str:
    """Compose the "bu istek bu belgeyle ilgili değil" reply. Never generated.

    Args:
        document_summary: The attached document's summary.
        document_type_label: The document's classified type, when known.

    Returns:
        The Turkish reply.
    """
    type_note = f" ({document_type_label})" if document_type_label else ""
    lines = [
        f"Bu istek, şu anda yüklü olan belge{type_note} ile ilgili değil, bu "
        "yüzden bu isteğe uygun bir taslak hazırlamadım.",
        "",
        f"Yüklü belgenin özeti: {document_summary or 'Özet mevcut değil.'}",
        "",
        "Bu belgeyle ilgili bir taslak veya analiz isteyebilir, ya da farklı bir "
        "konu için yeni bir belge yükleyebilirsiniz.",
    ]
    return "\n".join(lines)
