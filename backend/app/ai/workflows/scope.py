"""Domain admission control: does this request belong to the system at all?

The router (:mod:`app.ai.workflows.planner`) answers *which* of the system's
flows a message wants. It has never answered *whether* the message wants any
of them. Those are different questions, and conflating them is what let
"Çiğköfte kampanyası için bir metin yaz" reach the drafting pipeline: it
matches ``draft.explicit_request``'s ``"metni yaz"`` surface outright, so
every layer downstream -- fusion, the model tie-breaker, the writer agent --
correctly agreed it was a *drafting* request and dutifully produced a
marketing text. No amount of intent-table tuning fixes that, because the
intent was never wrong.

So scope is resolved separately, and it is resolved by *requiring positive
evidence* rather than by blacklisting topics. A deny-list of out-of-domain
subjects ("çiğköfte", "hava durumu", "futbol") is unbounded by construction
and fails on the first topic nobody thought of. The rule here is the
inverse:

* Small talk, courtesy, meta questions about the assistant, and questions
  about this conversation are **always** in scope -- they are how a user
  talks to any assistant, and refusing them is the failure the greeting
  rules in :mod:`app.ai.workflows.intent_rules` already exist to prevent.
* A request that *acts on* something -- drafting, analysing, revising --
  is in scope only when it is anchored: to the attached document, to the
  open draft, or to the official-correspondence/legislation domain
  vocabulary. An unanchored production request is out of scope no matter
  how confidently it reads as ``draft``.

``assess_scope_deterministic`` is free and reproducible and settles the
overwhelming majority of turns. Only genuinely unanchored production
requests -- the exact case worth spending a call on -- reach
``classify_scope_with_model``, which is the same fast tier the router's own
tie-breaker uses, and which degrades to the deterministic verdict on any
failure rather than blocking a legitimate request behind a provider outage.
"""

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient
from app.ai.workflows.intent_scorer import normalize
from app.ai.workflows.topic_words import content_words

logger = logging.getLogger(__name__)

__all__ = [
    "CAPABILITY_MANIFEST",
    "ScopeVerdict",
    "assess_scope_deterministic",
    "build_refusal_reply",
    "classify_scope_with_model",
    "resolve_scope",
]

#: Why a message was admitted or refused. Recorded on every decision so a
#: production refusal can be traced to the rule that produced it, the same
#: way ``PlanDecision.evidence`` traces an intent.
ScopeReason = Literal[
    "conversational",
    "system_question",
    "bare_command",
    "anchored_document",
    "anchored_draft",
    "domain_vocabulary",
    "model_admitted",
    "model_refused",
    "unanchored_request",
    "degraded",
]

#: Intents that *produce* something on the user's behalf. Only these are
#: subject to the anchoring requirement -- ``assist`` answers questions, and
#: an unanchored question is a normal thing to ask an assistant.
PRODUCTION_INTENTS = frozenset({"draft", "analyze", "revise"})

#: Vocabulary of official correspondence and public administration. A
#: production request carrying any of these is talking about this system's
#: subject matter even with nothing attached ("resmi yazı şablonu nasıl
#: olur"), so it is admitted without a model call.
#:
#: Deliberately *not* a topic classifier: it does not try to recognise every
#: in-domain subject, only the register. A request that is genuinely in
#: domain but phrased without any of these still gets its model call rather
#: than being refused on a lexicon miss.
DOMAIN_SURFACES: tuple[str, ...] = (
    "resmi yazi", "resmi yazisma", "ust yazi", "alt yazi", "evrak", "belge",
    "dilekce", "genelge", "tebligat", "teblig", "muzekkere", "tezkere",
    "mukabele", "olur", "onay yazisi", "cevap yazisi", "bilgilendirme yazisi",
    "kurum", "kurumsal", "idare", "idari", "kamu", "bakanlik", "mudurluk",
    "mudurlugu", "baskanlik", "baskanligi", "daire", "birim", "mudur",
    "mevzuat", "kanun", "yonetmelik", "yonerge", "teblig", "madde", "fikra",
    "bend", "sayili kanun", "hukuk", "hukuki", "yasal", "yasal dayanak",
    "basvuru", "sikayet", "talep", "itiraz", "bilgi edinme", "kvkk",
    "gizlilik derecesi", "tasnif disi", "hizmete ozel", "gelen evrak",
    "giden evrak", "havale", "sevk", "arz ederim", "rica ederim",
    "sayin", "muhatap", "konu satiri", "imza blogu", "ek listesi",
    "personel", "memur", "izin", "atama", "gorevlendirme", "yazisma",
)

#: Phrases that make a message about *this system* or *this conversation*
#: rather than about a topic at all. Always admitted -- these are exactly
#: what the assistant is for, and the pre-existing ``assist.*`` evidence
#: rules already treat them as first-class.
SYSTEM_SURFACES: tuple[str, ...] = (
    "ne yapabilirsin", "neler yapabilirsin", "yeteneklerin", "yetenekleri",
    "ne ise yararsin", "ne ise yarar", "nasil calisirsin", "nasil calisiyorsun",
    "nasil calisir", "sen kimsin", "kimsin", "sen nesin", "adin ne",
    "seni kim yapti", "hangi modeli", "sistem ne yapiyor", "bu sistem",
    "bu sistemde", "bu uygulama", "bu asistan", "nasil kullanilir",
    "nasil kullanabilirim", "yardim eder misin", "yardimci olur musun",
    "ne sordum", "ne demistim", "ne konustuk", "konusma gecmisi",
    "az once", "daha once", "onceki mesaj", "hatirliyor musun",
)

#: Bare social exchange. Length-gated by the caller, not by content: "selam"
#: is small talk, "Selam, çiğköfte kampanyası için metin yazar mısın?" is a
#: production request that happens to open politely.
CONVERSATIONAL_SURFACES: tuple[str, ...] = (
    "merhaba", "selam", "gunaydin", "iyi gunler", "iyi aksamlar",
    "iyi calismalar", "kolay gelsin", "nasilsin", "tesekkur", "tesekkurler",
    "sagol", "sag ol", "eyvallah", "rica ederim", "gorusuruz", "hosca kal",
    "gorusmek uzere", "peki", "tamam", "anladim", "evet", "hayir",
)

#: The bounded list of what this system does, in the user's own terms. Kept
#: here rather than only in ``prompts/templates/assistant.md`` because the
#: refusal path renders it deterministically -- a refusal must never be a
#: generation, or the model gets one more chance to do the thing it was just
#: told not to do.
CAPABILITY_MANIFEST: tuple[str, ...] = (
    "Yüklediğiniz evrakın türünü tespit edip üst verilerini (tarih, sayı, konu, "
    "muhatap) çıkarabilir ve resmî yazışma kurallarına uygunluğunu denetleyebilirim.",
    "Evrakın konusuyla ilgili kanun, yönetmelik ve mevzuat maddelerini tarayabilirim.",
    "Evraka resmî ve kurumsal bir Türkçe cevap taslağı hazırlayabilirim.",
    "Hazırlanan taslağı talimatınıza göre revize edebilirim.",
    "Taslağın kurum içinde hangi birime sevk edilmesi gerektiğini gerekçesiyle "
    "önerebilirim.",
    "Yüklü evrakın içeriğine dair sorularınızı doğrudan evrak metnine dayanarak "
    "yanıtlayabilirim.",
)

#: Longest message still treated as pure social exchange on the strength of a
#: conversational surface alone. "Selam" and "iyi çalışmalar" are inside it;
#: a greeting with a real request bolted onto it is not, and falls through to
#: the anchoring test like any other request.
_CONVERSATIONAL_WORD_LIMIT = 6


@dataclass(frozen=True)
class ScopeVerdict:
    """Whether a message is this system's business, and why.

    Attributes:
        in_scope: False only when the request should not run at all. A
            refusal is a real outcome, not an error -- see
            ``build_refusal_reply``.
        reason: Which rule settled it (see ``ScopeReason``).
        source: ``"deterministic"`` or ``"model"``, mirroring the split every
            other decision layer in this package reports.
        detail: Short Turkish note for the audit trail. Never shown verbatim
            to the user; the refusal text is composed separately.
    """

    in_scope: bool
    reason: ScopeReason
    source: Literal["deterministic", "model"] = "deterministic"
    detail: str = ""


class ScopeOutput(BaseModel):
    """The fast-tier model's verdict on an unanchored production request."""

    in_scope: bool = Field(
        description=(
            "Bu istek bir resmî evrak/yazışma karar destek sisteminin görev "
            "alanına giriyor mu? Resmî yazışma, evrak, mevzuat, kamu idaresi "
            "ile ilgiliyse true. Pazarlama metni, reklam, sosyal medya içeriği, "
            "yaratıcı yazarlık, genel kültür, kod yazma gibi konularsa false."
        )
    )


def _contains(normalized: str, surfaces: tuple[str, ...]) -> bool:
    """Whether any surface appears in the already-normalised message."""
    padded = f" {normalized} "
    return any(f" {surface}" in padded for surface in surfaces)


def assess_scope_deterministic(
    message: str,
    intent: str,
    *,
    has_document: bool,
    has_active_draft: bool,
) -> ScopeVerdict:
    """Settle scope from the message alone, where that is possible.

    Args:
        message: The user's raw message.
        intent: The intent the router resolved for it. Only
            ``PRODUCTION_INTENTS`` are subject to the anchoring requirement.
        has_document: Whether a document is attached this turn.
        has_active_draft: Whether ``SessionFocus.active_draft`` is set.

    Returns:
        A verdict. ``in_scope=False`` with reason ``"unanchored_request"`` is
        the one outcome the caller may want to escalate to a model rather
        than act on directly (see ``resolve_scope``); every other outcome is
        final.
    """
    normalized = normalize(message)

    if not normalized:
        return ScopeVerdict(True, "conversational", detail="Boş mesaj.")

    if _contains(normalized, SYSTEM_SURFACES):
        return ScopeVerdict(
            True, "system_question", detail="Sistemin kendisi hakkında bir soru."
        )

    if intent not in PRODUCTION_INTENTS:
        # An `assist` turn is a question, and a question is admitted on its
        # face. The assistant's own prompt is what declines to *answer* an
        # off-topic one; refusing it here as well would mean a user could
        # not even ask what the system covers.
        if len(normalized.split()) <= _CONVERSATIONAL_WORD_LIMIT and _contains(
            normalized, CONVERSATIONAL_SURFACES
        ):
            return ScopeVerdict(True, "conversational", detail="Selamlama/nezaket.")
        return ScopeVerdict(True, "conversational", detail="Soru/sohbet turu.")

    # From here on the message asked the system to *produce* something, so
    # it needs an anchor.
    if intent == "revise" and has_active_draft:
        return ScopeVerdict(
            True, "anchored_draft", detail="Açık taslak üzerinde revizyon."
        )

    # A message that is *nothing but* the drafting/revision command itself
    # ("Cevap yaz.") carries no evidence of being about anything other than
    # this system's own subject matter -- there is no extra noun phrase left
    # to be off-topic *about*. This is what keeps the gate from refusing the
    # bare imperative the router's own module docstring uses as its worked
    # example of an unambiguous draft request; only a command with something
    # else attached to it ("Cevap yaz, çiğköfte kampanyası için") reaches the
    # anchoring checks below at all.
    if not content_words(message):
        return ScopeVerdict(
            True, "bare_command", detail="Salt üretim komutu; ek bir konu içermiyor."
        )

    if _contains(normalized, DOMAIN_SURFACES):
        return ScopeVerdict(
            True, "domain_vocabulary", detail="Resmî yazışma/mevzuat terminolojisi."
        )

    if has_document:
        # A document is an anchor, but a weak one on its own: it makes the
        # request *plausibly* about the document without establishing that
        # it is. `app.ai.workflows.relevance` is the check that actually
        # compares the request against the document's contents, and it runs
        # once classification has produced a summary to compare against --
        # which is strictly later than here.
        return ScopeVerdict(
            True, "anchored_document", detail="Yüklü belge bağlamında üretim isteği."
        )

    return ScopeVerdict(
        False,
        "unanchored_request",
        detail=(
            "Üretim isteği; ne yüklü bir belgeye, ne açık bir taslağa, ne de "
            "resmî yazışma/mevzuat alanına bağlanıyor."
        ),
    )


async def classify_scope_with_model(
    llm_client: BaseLLMClient, message: str
) -> Optional[bool]:
    """Ask the fast tier whether an unanchored request is in domain.

    Args:
        llm_client: Fast-tier client, the same one the router's tie-breaker
            uses.
        message: The user's message.

    Returns:
        The model's verdict, or ``None`` when the call itself failed --
        distinct from ``False`` on purpose, exactly like
        ``classify_intent_with_model``'s ``"model_failed"``: a provider
        outage must not read as a refusal.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="ScopeClassifier",
        description="Decides whether a request falls inside the EKDS domain.",
        system_prompt=(
            "Sen bir Evrak Karar Destek Sistemi'nin kapsam denetleyicisisin. "
            "Sana verilen isteğin bu sistemin görev alanına girip girmediğine "
            "karar ver. Yalnızca yapılandırılmış JSON döndür.\n"
            "Görev alanı: resmî yazışma, evrak analizi, dilekçe/genelge/tebligat, "
            "kamu idaresi süreçleri, mevzuat ve bunlara dair taslak hazırlama.\n"
            "Görev alanı DIŞI: pazarlama/reklam/kampanya metni, sosyal medya "
            "içeriği, yaratıcı yazarlık (şiir, hikâye), genel kültür, haber, "
            "yemek/tarif, spor, kod yazma, kişisel yazışma.\n"
            "Kararsızsan görev alanına girmediğini varsayma; yalnızca açıkça "
            "alan dışıysa false döndür."
        ),
    )

    try:
        result: ScopeOutput = await agent.run_structured(
            messages=f'İstek: "{message}"\n\nBu istek görev alanına giriyor mu?',
            response_model=ScopeOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.in_scope
    except Exception:
        logger.warning("Scope classification failed; falling back to deterministic verdict.")
        return None


async def resolve_scope(
    message: str,
    intent: str,
    *,
    has_document: bool,
    has_active_draft: bool,
    llm_client: Optional[BaseLLMClient] = None,
) -> ScopeVerdict:
    """Resolve scope, escalating only the case a model call can improve.

    Args:
        message: The user's message.
        intent: The router's resolved intent.
        has_document: Whether a document is attached this turn.
        has_active_draft: Whether a draft is open.
        llm_client: Fast-tier client. Omitted means the deterministic verdict
            stands on its own -- which is a *stricter* system, not a broken
            one: an unanchored production request is refused without the
            model getting a chance to admit it.

    Returns:
        The final verdict.
    """
    verdict = assess_scope_deterministic(
        message, intent, has_document=has_document, has_active_draft=has_active_draft
    )
    if verdict.in_scope or llm_client is None:
        return verdict

    admitted = await classify_scope_with_model(llm_client, message)
    if admitted is None:
        # The call broke, not the request. Keeping the deterministic refusal
        # would turn an Ollama outage into "the system refuses to draft
        # anything", so this admits instead and lets the ordinary pipeline
        # (and the writer's own grounding requirements) handle it.
        return ScopeVerdict(
            True,
            "degraded",
            source="model",
            detail="Kapsam modeli yanıt vermedi; istek kapsam içi sayıldı.",
        )
    if admitted:
        return ScopeVerdict(
            True, "model_admitted", source="model", detail="Model kapsam içi buldu."
        )
    return ScopeVerdict(
        False, "model_refused", source="model", detail="Model kapsam dışı buldu."
    )


def build_refusal_reply(document_summary: str = "") -> str:
    """Compose the out-of-scope reply. Deterministic, never generated.

    A refusal produced by the same model that was just asked to write the
    off-topic text is a refusal with an escape hatch. This renders from
    ``CAPABILITY_MANIFEST`` instead, so what the system claims it can do is
    the same string every time and cannot drift from what it actually does.

    Args:
        document_summary: The attached document's summary, when one is
            attached. Included so a user who uploaded a document and then
            asked something unrelated is not left wondering whether the
            upload registered.

    Returns:
        The Turkish reply.
    """
    lines = [
        "Bu istek benim görev alanımın dışında kalıyor. Ben bir **Evrak Karar "
        "Destek Sistemi** asistanıyım ve yalnızca resmî yazışma, evrak ve "
        "mevzuat işlerinde yardımcı olabiliyorum.",
        "",
        "Yapabileceklerim:",
        *(f"- {item}" for item in CAPABILITY_MANIFEST),
    ]
    if document_summary:
        lines += [
            "",
            f"Bu arada, yüklü olan belgenin özeti şu: {document_summary}",
        ]
    return "\n".join(lines)
