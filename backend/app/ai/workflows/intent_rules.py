"""Declarative evidence rules for intent resolution.

The rules a message is scored against, kept apart from the scoring itself so
that adding a phrase is a data change with no control flow attached to it.

Why this replaces an ordered keyword cascade
--------------------------------------------
The previous resolver checked keyword groups in a fixed order and returned on
the first hit. That makes the *order* the decision, which is unfixable by
reordering: with draft checked first, "Resmi yazı ne demek?" starts a drafting
pipeline; with analyze first, "analiz sonrası taslak hazırla" resolves to
analysis instead. The measured baseline scored `inversion` at 0.00 -- eight
cases out of eight, every one landing on `draft` with `source=keyword`.

Scoring fixes this because evidence accumulates instead of short-circuiting. A
message carrying both a drafting phrase and an analysis phrase ends up with two
comparable scores and a small margin, and a small margin is information: it
means "these are close", which is either a compound request or a case to escalate.

The other measured failure, `precedence` at 0.00, has the same root: the
greeting rule was gated on ``document_id is None``, so "Merhaba" with a document
attached fell past every branch and abstained. Here document state is a
*weight*, never a gate -- ``requires_document`` exists for rules that genuinely
cannot apply otherwise (asking about a document's contents), and greetings do
not use it.
"""

from dataclasses import dataclass
from typing import Literal, Optional

Intent = Literal["draft", "analyze", "assist", "draft_revision"]

RuleKind = Literal["phrase", "structural"]


@dataclass(frozen=True)
class EvidenceRule:
    """One piece of evidence for one intent.

    Attributes:
        id: Stable identifier, reported on every decision so a production
            outcome can be traced back to the exact rule that drove it.
        intent: The intent this evidence argues for.
        weight: How strongly. Calibrated by tier rather than per rule -- see the
            weight constants below.
        surfaces: Normalised phrases (ASCII-folded, lowercase) that fire it.
        requires_document: When True the rule only applies with a document
            attached; when False only without one; when None the document state
            is irrelevant. Used sparingly -- a gate here is what broke the
            greeting path.
        requires_last_draft: When True the rule only applies when the
            conversation has a draft to revise (see planning_graph.py's
            `last_draft`); when None the state is irrelevant. Every
            `draft_revision` rule sets this -- without a prior draft "son
            taslağı kısalt" has nothing to act on, and must fall through to
            whatever else the message's evidence supports instead.
    """

    id: str
    intent: Intent
    weight: float
    surfaces: tuple[str, ...] = ()
    kind: RuleKind = "phrase"
    requires_document: Optional[bool] = None
    requires_last_draft: Optional[bool] = None


#: An unambiguous imperative: the user is asking for the thing, not about it.
WEIGHT_EXPLICIT = 3.0
#: A domain phrase that suggests an intent but also appears in questions *about*
#: that intent ("üst yazı ne demek"). Strong enough to win on its own, weak
#: enough to be overturned by a competing signal.
WEIGHT_DOMAIN = 1.6
#: A contextual hint: sentence shape, message length, the previous turn.
WEIGHT_HINT = 1.0
#: A counter-signal that argues *against* an intent rather than for another one.
#: Sized to outweigh an explicit phrase plus a domain noun together (3.0 + 1.6),
#: because "Taslak oluşturma süreci nasıl işliyor?" matches both -- the substring
#: "taslak olustur" is inside "taslak oluşturma" -- and still is not a request to
#: draft anything.
WEIGHT_COUNTER = -4.8


DRAFT_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="draft.explicit_request",
        intent="draft",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "taslak hazirla", "taslak olustur", "taslak cikar", "taslagi hazirla",
            "yazi yaz", "yazi hazirla", "yazi olustur", "yaziyi hazirla",
            "cevap yaz", "cevap hazirla", "cevabi hazirla", "cevap olustur",
            "cevap yazisi olustur", "cevabini yaz", "cevabini hazirla",
            "yanit yaz", "yanit hazirla", "yanitini hazirla",
            "kaleme al", "metni yaz", "metni olustur", "metni duzenle",
            "metni uret", "metnini uret", "yazisma hazirla", "yazisma kurgula",
            "dilekceye cevap", "yaziya dok", "kaleme alinmasini",
            "duzenlemeni", "kurgular misin", "tanzim et", "mukabelede bulun",
            "mukabele metni", "mukabele hazirla", "bildirim yapacak bir yazisma",
            "yazi cikar", "cevabi duzenle", "cevabini duzenle", "cevabi yaz",
        ),
    ),
    EvidenceRule(
        id="draft.domain_noun",
        intent="draft",
        weight=WEIGHT_DOMAIN,
        surfaces=(
            "taslak", "ust yazi", "resmi yazi", "bilgilendirme metni",
            "cevap yazisi", "tebligat metni", "muzekkere", "tezkere", "mukabele",
        ),
    ),
)

ANALYZE_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="analyze.explicit_request",
        intent="analyze",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "analiz et", "incele", "inceleyip", "siniflandir", "turunu belirle",
            "ozetle", "ozet cikar", "degerlendir", "kontrol et", "denetle",
            "gozden gecir", "irdele", "tespit et", "tespit etmeni",
            "uygunlugunu", "uygunluk denetimi", "mevzuata uygun", "kurallara uy",
            "eksik alan", "eksik bilgi", "eksiklikleri", "bir bak",
            "olup olmadigina", "hangi kategoriye", "bulgularini raporla",
        ),
    ),
    EvidenceRule(
        id="analyze.domain_noun",
        intent="analyze",
        weight=WEIGHT_DOMAIN,
        surfaces=("uygunluk", "evrak analizi", "belge analizi"),
    ),
)

#: `chat` and `document_qa` used to be two separate intents, each with its own
#: score bucket, and a chunk of this module's history is rules that exist only
#: to arbitrate between them: a memory-recall question must beat a document
#: question, a politely-phrased request must not be read as a content lookup.
#: Both now resolve to the same `assist` bucket (a single agent that answers
#: conversationally and reaches for retrieval tools itself when it needs to),
#: so that arbitration has nothing left to arbitrate -- evidence for either
#: reading simply accumulates in the same score instead of competing. Only the
#: two rules below that were pure tie-breakers (`document_qa.request_softener_
#: counter`, `document_qa.memory_recall_counter` in the pre-merge version) were
#: dropped; every rule that contributed genuine positive evidence survives,
#: renamed onto `assist`.
ASSIST_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="assist.greeting",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "merhaba", "selam", "gunaydin", "iyi gunler", "iyi aksamlar",
            "iyi calismalar", "gorusuruz", "hosca kal", "kolay gelsin",
        ),
    ),
    EvidenceRule(
        id="assist.courtesy",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "tesekkur", "tesekkurler", "sagol", "sag ol", "eyvallah",
            "cok iyi oldu", "yardimci oldun",
        ),
    ),
    EvidenceRule(
        id="assist.about_the_assistant",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "nasilsin", "kimsin", "sen kimsin", "ne yapabilirsin",
            "neler yapabilirsin", "nasil calisir", "nasil calisiyor",
            "yardim eder misin", "ne ise yarar",
        ),
    ),
    #: The counter-signal that makes `inversion` solvable. These phrases mark a
    #: message as being *about* a concept rather than a request to produce one:
    #: "ne demek", "fark nedir", "hangi durumlarda kullanilir". They subtract
    #: from whichever domain noun fired, so "Üst yazı ne demek?" lands on
    #: `assist` without the draft phrases needing to be weakened for every
    #: other case.
    #:
    #: Bare "açıklar mısın" / "anlatır mısın" used to be listed here too, on the
    #: assumption that asking for an explanation is always about a concept. It
    #: is not: "Şu belgeye bakıp durumu anlatır mısın?" asks the same thing
    #: about a specific attached document, which is an analysis request, not a
    #: definitional one. Removed -- every existing case that used either
    #: phrase also carries its own definitional marker ("ne demek", "nasıl
    #: çalışır") and still resolves correctly without it.
    EvidenceRule(
        id="assist.definitional_question",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            # Bare "nedir" is deliberately absent: "Evrakın konusu nedir?" is a
            # question about a document's contents, not about a concept.
            "ne demek", "ne anlama", "fark nedir", "farki nedir",
            "arasindaki fark", "hangi durumlarda", "ne zaman kullanilir",
            "nasil isliyor", "nasil yapilir", "ne dusunuyorsun",
            "ornegi nedir",
        ),
    ),
    #: Only meaningful when a document is attached; asking what a document
    #: says is not a plausible reading of a message with nothing to read.
    #: Possessives ("belgenin", "evrakın") are deliberately absent: they are
    #: just as common in analysis requests ("Belgenin hangi kategoriye
    #: girdiğini tespit et") and let this rule outscore analyze there.
    EvidenceRule(
        id="assist.about_the_document",
        intent="assist",
        weight=WEIGHT_DOMAIN,
        surfaces=(
            "bu belgede", "belgede", "evrakta", "bu evrak", "bu yazi",
            "belgeyi kim", "talep edilen", "yazi kime", "belgede gizlilik",
        ),
        requires_document=True,
    ),
)

#: Phrases that make a message about *this conversation's own history*. Kept as
#: its own tier because a recall question must reach `assist` (unrestricted
#: history access) whatever else the message contains -- a document being
#: attached must never turn a question about the conversation into a question
#: about the document.
MEMORY_RECALL_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="assist.memory_recall",
        intent="assist",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "az once", "biraz once", "az evvel", "biraz evvel", "demin",
            "evvelce", "evvelki", "gecen sefer", "daha once", "onceki", "onceki mesaj",
            "onceki turda", "onceki sorumda", "ilk mesajimda", "ilk talebi",
            "demistim", "dedim mi", "demis miydim", "soylemis miydim",
            "sormus muydum", "sordum mu", "sordugum", "sorduğum soruyu",
            "hatirliyor musun", "hatirliyor musunuz", "animsiyor musun",
            "hatirla", "yukarida ne dedim", "yukarida ne yazdim",
            "yukarida bahsettigim", "bu konusmada", "bu sohbette",
            "bu diyalogda", "sohbetimizin basinda", "buraya kadar",
            "sana ne sordum", "sana ne demistim", "en son ne sordum",
            "en son sana ne", "konusma gecmisi", "konusma gecmisimizi",
            "gecmis mesajlarda", "neler konustugumuzu", "ne konusmustuk",
            "konustugumuz konuyu", "bahsetmistim", "bahsettim",
            "vermistim", "verdigin cevabi", "tekrar eder misin",
            "tekrarlayabilir misin",
        ),
    ),
)

#: Editing an already-produced draft, as opposed to `draft` (produce a new one
#: from scratch via classification -> draft -> routing). Gated on
#: `requires_last_draft=True` so these phrases carry no evidence at all in a
#: conversation that has no draft yet -- "bu belgeyi kısalt" without a prior
#: draft has nothing to act on, and must resolve like any other message.
DRAFT_REVISION_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        id="draft_revision.explicit_request",
        intent="draft_revision",
        weight=WEIGHT_EXPLICIT,
        surfaces=(
            "son taslakta", "son taslagi", "son taslaktaki", "bu taslagi",
            "taslaktaki", "taslakta degistir", "taslagi degistir",
            "taslagi duzelt", "taslagi revize et", "taslagi kisalt",
            "taslagi uzat", "taslaga ekle", "taslaktan cikar",
            "taslagin tonunu", "tonunu daha resmi", "daha resmi bir dille",
            "taslagi tekrar yaz", "taslagi yeniden yaz", "cumleyi degistir",
            "paragrafi kisalt", "paragrafi degistir", "paragrafi uzat",
            "ifadeleri degistir", "kelimeleri degistir", "ben yerine biz",
            "birinci tekil yerine", "resmi bir uslupla tekrar",
        ),
        requires_last_draft=True,
    ),
)

#: A message that both looks like a question and has a document attached is
#: evidence for `assist` even when it matches no lexical surface above (e.g.
#: "Evrakın konusu nedir?") -- see `intent_scorer.score_intents`'s structural
#: `assist.question_with_document` rule, which is not a lexical surface rule
#: and so is not in this table.
ALL_RULES: tuple[EvidenceRule, ...] = (
    *DRAFT_RULES,
    *ANALYZE_RULES,
    *ASSIST_RULES,
    *MEMORY_RECALL_RULES,
    *DRAFT_REVISION_RULES,
)

#: A short affirmative continues whatever the previous turn was about.
CONTINUATION_SURFACES: tuple[str, ...] = (
    "evet", "olur", "tamam", "tamamdir", "onayliyorum", "onaylıyorum",
    "devam", "devam et", "devam edebilirsin", "hazirla", "yap", "lutfen",
    "peki", "elbette",
)

#: Only these intents make sense to silently continue; a bare "evet" after an
#: assist turn has no unambiguous follow-up action. `draft_revision` is
#: continuable for the same reason `draft` is -- a short affirmative after
#: "taslağı kısaltayım mı?" should continue revising, not re-score from
#: scratch.
CONTINUABLE_INTENTS = frozenset({"draft", "analyze", "draft_revision"})

#: Question markers, used as a shape hint rather than a routing decision.
#: Bare "ne" is deliberately absent: "ne gerekiyorsa onu uygula" is an
#: instruction, not a question, and treating it as one made an
#: under-specified command resolve to document Q&A instead of escalating.
QUESTION_SURFACES: tuple[str, ...] = (
    "mi", "mu", "midir", "mudur", "neden", "nasil", "kim",
    "kimden", "kime", "kac", "hangi", "nerede", "nereye", "ne zaman",
    "var mi", "neydi", "nedir", "hangisiydi",
)
