"""Intent resolution for the master workflow.

The system has four fixed flows and the choice between them is a lookup, not a
reasoning task. It used to be made by a full structured LLM call against the
orchestrator prompt, which cost a round trip plus a Pydantic retry loop on the
critical path -- and was unreliable enough to need sixty lines of defensive
parsing (``handle_nested_hallucinations``) to patch up its output shape.

This module decides deterministically from the message and the presence of a
document. Only genuinely ambiguous messages fall through to a model, and that
call is a single label from the fast tier rather than a nested JSON object.
"""

import logging
import re
import unicodedata
from typing import Literal, NamedTuple, Optional

from pydantic import BaseModel, Field

from app.ai.llms.base import BaseLLMClient

logger = logging.getLogger(__name__)

Intent = Literal["draft", "analyze", "document_qa", "chat"]

#: Step sequences per intent.
#:
#: Note the absence of a separate ``rag`` step in the draft flow. The
#: classification sub-graph already retrieves legislation for the document and
#: puts it in ``mevzuat_documents``; running the RAG graph afterwards repeated
#: the same retrieval behind an extra query-rewrite LLM call and threw the first
#: result away.
PLAN_BY_INTENT: dict[str, list[str]] = {
    "draft": ["classification", "draft", "routing"],
    "analyze": ["classification"],
    "document_qa": ["document_qa"],
    "chat": ["chat"],
}

REASONING_BY_INTENT: dict[str, str] = {
    "draft": "Resmî yazı talebi tespit edildi: evrak analizi, taslak üretimi ve birim yönlendirmesi çalıştırılacak.",
    "analyze": "Evrak analizi talebi tespit edildi: sınıflandırma ve uygunluk denetimi çalıştırılacak.",
    "document_qa": "Yüklü bir belge hakkında soru tespit edildi: belge soru-cevap akışı çalıştırılacak.",
    "chat": "Evrak işlemi gerektirmeyen genel bir mesaj tespit edildi: sohbet akışı çalıştırılacak.",
}

DRAFT_KEYWORDS = (
    "taslak",
    "yazi yaz",
    "yazi hazirla",
    "yazi olustur",
    "cevap yaz",
    "cevap hazirla",
    "cevabi hazirla",
    "cevap olustur",
    "ust yazi",
    "resmi yazi",
    "yaziyi hazirla",
    "bilgilendirme metni",
    "dilekceye cevap",
    "yanit yaz",
    "yanit hazirla",
    "kaleme al",
    "metni yaz",
    "yazisma hazirla",
)

ANALYZE_KEYWORDS = (
    "analiz et",
    "incele",
    "siniflandir",
    "turunu belirle",
    "eksik alan",
    "eksik bilgi",
    "uygunluk",
    "ozetle",
    "ozet cikar",
    "degerlendir",
    "kontrol et",
    "mevzuata uygun",
)

#: Openers that are unambiguously conversational regardless of context.
CHAT_KEYWORDS = (
    "merhaba",
    "selam",
    "gunaydin",
    "iyi gunler",
    "iyi aksamlar",
    "tesekkur",
    "sagol",
    "nasilsin",
    "kimsin",
    "ne yapabilirsin",
    "neler yapabilirsin",
    "yardim",
    "nasil calisir",
    "gorusuruz",
    "hosca kal",
)

#: A short affirmative reply to "taslak hazırlayayım mı?" or "analiz edeyim
#: mi?" continues whatever the previous turn's intent was, rather than
#: falling through to the "short message -> chat" default. Without this, "evet,
#: hazırla" after a draft offer resolved to plain conversation.
CONTINUATION_KEYWORDS = (
    "evet",
    "olur",
    "tamam",
    "onayliyorum",
    "devam et",
    "devam",
    "hazirla",
    "yap",
    "lutfen",
)

#: Only these intents make sense to silently continue; a bare "evet" after a
#: chat/document_qa turn has no unambiguous follow-up action.
_CONTINUABLE_INTENTS = frozenset({"draft", "analyze"})

QUESTION_MARKERS = (
    "mi",
    "mu",
    "mü",
    "mı",
    "ne ",
    "neden",
    "nasil",
    "kim",
    "kac",
    "hangi",
    "nerede",
    "ne zaman",
    "var mi",
    "kimden",
    "kime",
)

#: Phrases that make a message about *this conversation's own history* rather
#: than a document's content or a fresh topic. Firing this must send the
#: message to `chat` (unrestricted history access) regardless of whether a
#: document happens to be attached -- a document being attached must never
#: turn a question about the conversation itself into a document question.
MEMORY_RECALL_MARKERS = (
    "az once",
    "biraz once",
    "az evvel",
    "demistim",
    "dedim mi",
    "demis miydim",
    "soylemis miydim",
    "sormus muydum",
    "sordum mu",
    "hatirliyor musun",
    "hatirliyor musunuz",
    "hatirla",
    "onceki mesaj",
    "onceki mesajimda",
    "onceki sorumda",
    "yukarida ne dedim",
    "yukarida ne yazdim",
    "bu konusmada",
    "bu sohbette",
    "sana ne sordum",
    "sana ne demistim",
    "en son ne sordum",
    "en son sana ne",
    "konusma gecmisi",
    "gecmis mesajlarda",
    "ilk mesajimda",
    "daha once ne sordum",
    "daha once sordugum",
    "daha once konustuk",
    "daha once bahsettim",
)

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


class PlanDecision(NamedTuple):
    """The resolved execution plan for one user message."""

    steps: list[str]
    intent: Intent
    reasoning: str
    source: str


class IntentOutput(BaseModel):
    """Single-label intent classification, used only for ambiguous messages."""

    intent: Literal["draft", "analyze", "document_qa", "chat"] = Field(
        description=(
            "Kullanıcının niyeti. draft: resmi yazı/taslak hazırlanması isteniyor. "
            "analyze: evrakın analiz edilmesi isteniyor. "
            "document_qa: yüklü belge hakkında soru soruluyor. "
            "chat: genel sohbet."
        )
    )


def normalize(text: str) -> str:
    """Fold Turkish text to lowercase ASCII for keyword matching.

    Args:
        text: Raw user text.

    Returns:
        Lowercase ASCII with punctuation collapsed to single spaces.
    """
    folded = (text or "").translate(_TURKISH_MAP)
    folded = unicodedata.normalize("NFKD", folded)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    """Report whether any needle appears in the normalized haystack."""
    return any(needle in haystack for needle in needles)


def _looks_like_question(raw: str, normalized: str) -> bool:
    """Heuristically decide whether the message asks something.

    Args:
        raw: The original message, for punctuation.
        normalized: The folded message, for token checks.

    Returns:
        True when the message reads as a question.
    """
    if "?" in raw:
        return True
    return _contains_any(f" {normalized} ", tuple(f" {m.strip()} " for m in QUESTION_MARKERS))


def _is_memory_recall_question(normalized: str) -> bool:
    """Heuristically decide whether the message asks about earlier turns in
    *this* conversation, rather than a document or a fresh topic.

    Args:
        normalized: The folded message, for token checks.

    Returns:
        True when the message reads as a memory-recall question.
    """
    return _contains_any(
        f" {normalized} ", tuple(f" {m.strip()} " for m in MEMORY_RECALL_MARKERS)
    )


def resolve_plan_deterministic(
    message: str, document_id: Optional[str], previous_intent: Optional[str] = None
) -> Optional[PlanDecision]:
    """Resolve the plan without a model, when the message allows it.

    Precedence is deliberate: an explicit drafting request wins over everything,
    because "bu belgeye cevap yazısı hazırla" is both a document reference and a
    drafting request and the drafting flow is the superset.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        previous_intent: The intent resolved for this thread's previous turn,
            when known. Lets a short affirmative ("evet, hazırla") continue a
            draft/analyze offer instead of falling through to plain chat.

    Returns:
        A decision, or None when the message is ambiguous.
    """
    normalized = normalize(message)

    if not normalized:
        return PlanDecision(
            list(PLAN_BY_INTENT["chat"]), "chat", REASONING_BY_INTENT["chat"], "empty"
        )

    if _contains_any(normalized, DRAFT_KEYWORDS):
        return PlanDecision(
            list(PLAN_BY_INTENT["draft"]), "draft", REASONING_BY_INTENT["draft"], "keyword"
        )

    if _contains_any(normalized, ANALYZE_KEYWORDS):
        return PlanDecision(
            list(PLAN_BY_INTENT["analyze"]),
            "analyze",
            REASONING_BY_INTENT["analyze"],
            "keyword",
        )

    if (
        previous_intent in _CONTINUABLE_INTENTS
        and len(normalized.split()) <= 6
        and _contains_any(normalized, CONTINUATION_KEYWORDS)
    ):
        return PlanDecision(
            list(PLAN_BY_INTENT[previous_intent]),
            previous_intent,  # type: ignore[arg-type]
            REASONING_BY_INTENT[previous_intent] + " (önceki isteğin devamı)",
            "continuation",
        )

    # A question about the conversation itself must never be treated as a
    # document question just because a document happens to be attached --
    # unconditional on document_id, unlike the document-question branch below.
    if _is_memory_recall_question(normalized):
        return PlanDecision(
            list(PLAN_BY_INTENT["chat"]),
            "chat",
            REASONING_BY_INTENT["chat"] + " (konuşmanın kendisine dair bir soru tespit edildi)",
            "memory_recall",
        )

    # A greeting with no document attached needs no further thought.
    if document_id is None and _contains_any(normalized, CHAT_KEYWORDS):
        return PlanDecision(
            list(PLAN_BY_INTENT["chat"]), "chat", REASONING_BY_INTENT["chat"], "keyword"
        )

    if document_id and _looks_like_question(message, normalized):
        return PlanDecision(
            list(PLAN_BY_INTENT["document_qa"]),
            "document_qa",
            REASONING_BY_INTENT["document_qa"],
            "document_question",
        )

    # No document and nothing document-shaped in the message: conversation.
    if document_id is None and len(normalized.split()) <= 4:
        return PlanDecision(
            list(PLAN_BY_INTENT["chat"]), "chat", REASONING_BY_INTENT["chat"], "short_message"
        )

    return None


async def classify_intent_with_model(
    llm_client: BaseLLMClient, message: str, document_id: Optional[str]
) -> Intent:
    """Fall back to a one-label model call for genuinely ambiguous messages.

    Args:
        llm_client: Fast-tier LLM client.
        message: The user's message.
        document_id: Storage path of an attached document, when present.

    Returns:
        The classified intent, defaulting to a safe value on failure.
    """
    from app.ai.agents.base import BaseAgent

    agent = BaseAgent(
        llm_client=llm_client,
        name="IntentClassifier",
        description="Classifies a user message into one of four workflow intents.",
        system_prompt=(
            "Kullanıcı mesajını dört niyetten birine ata. Yalnızca yapılandırılmış "
            "JSON döndür, açıklama yazma.\n"
            "- draft: resmî yazı, cevap yazısı, üst yazı veya taslak hazırlanması isteniyor.\n"
            "- analyze: bir evrakın analiz edilmesi, sınıflandırılması veya eksiklerinin "
            "bulunması isteniyor.\n"
            "- document_qa: yüklü bir belgenin içeriği hakkında soru soruluyor.\n"
            "- chat: yukarıdakilerin hiçbiri; genel sohbet veya sistem hakkında soru."
        ),
    )

    prompt = (
        f'Mesaj: "{message}"\n'
        f"Sisteme yüklü bir belge var mı: {'evet' if document_id else 'hayır'}\n\n"
        "Bu mesajın niyetini belirle."
    )

    try:
        result: IntentOutput = await agent.run_structured(
            messages=prompt,
            response_model=IntentOutput,
            temperature=0.0,
            max_retries=1,
        )
        return result.intent
    except Exception:
        logger.warning("Intent classification failed; falling back by context.")
        # Safe default: the cheapest flow that can still answer. With a document
        # attached that is Q&A; without one it is conversation. Never the full
        # four-step pipeline, which is what the old fallback chose and which
        # turned every planner hiccup into the slowest possible response.
        return "document_qa" if document_id else "chat"


async def resolve_plan(
    message: str,
    document_id: Optional[str],
    llm_client: Optional[BaseLLMClient] = None,
    previous_intent: Optional[str] = None,
) -> PlanDecision:
    """Resolve the execution plan for a user message.

    Args:
        message: The user's message.
        document_id: Storage path of an attached document, when present.
        llm_client: Fast-tier client for the ambiguous case. When omitted, an
            ambiguous message resolves by context instead of by model.
        previous_intent: The intent resolved for this thread's previous turn,
            when known -- enables the short-affirmative continuation rule.

    Returns:
        The execution plan and the rationale shown to the user.
    """
    decided = resolve_plan_deterministic(message, document_id, previous_intent)
    if decided is not None:
        logger.info(
            "Plan resolved deterministically (%s): %s", decided.source, decided.steps
        )
        return decided

    if llm_client is None:
        intent: Intent = "document_qa" if document_id else "chat"
        source = "context_default"
    else:
        intent = await classify_intent_with_model(llm_client, message, document_id)
        source = "model"

    logger.info("Plan resolved via %s: intent=%s", source, intent)
    return PlanDecision(
        list(PLAN_BY_INTENT[intent]), intent, REASONING_BY_INTENT[intent], source
    )
