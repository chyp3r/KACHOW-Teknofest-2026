"""Deterministic resolution of who is writing to whom, before a draft exists.

``app.ai.workflows.draft_graph._build_brief`` renders ``Muhatap``/``Gönderen
Kurum`` from the incoming document's classification, but never states which
direction those two names point relative to the *writer*. For a
document-less request the classification carries neither at all. Either way
the writer prompt has nothing telling it which proper noun in the user's
own text is the sender and which is the addressee -- so it puts the only
name it sees ("KACMAK ekibi olarak") in the one slot the prompt does
describe, ``Muhatap``, producing a draft addressed *to* the requesting team
instead of written *by* it.

This module is the fix: a small set of writing-style slots (who's writing,
who it's going to, first-person-plural vs. institutional voice, closing
formula) resolved deterministically from the user's message and the
document's own classification, asked about only when unresolved, and never
by a model -- see :func:`resolve_brief`'s docstring for why. Same two-piece
shape as ``app.ai.workflows.correspondence``: a resolver
(``resolve_brief``) and a prompt renderer (``format_writing_brief``).

Every resolver call lands in one of three tiers, not two:

* **Confident** -- a strong, specific signal (an explicit "X ekibi olarak",
  a document's own header field, or -- for ``muhatap`` -- a single named
  addressee said in the same breath as an actual drafting verb, e.g.
  "Ahmet Yılmaz'a bir izin yazısı hazırla"; see ``_resolve_muhatap``'s own
  docstring). Never asked about at all.
* **Suggested** -- a weaker signal (a bare capitalized phrase, an inferred
  hierarchy guess, more than one named candidate) worth surfacing, but not
  worth silently trusting. Still asked about, but the guess rides along as
  the question's first option, labelled "(Önerilen)", and the question
  itself is phrased as an explicit confirmation ("Önerilen muhatap: X. Bu
  doğru mu?") -- a click confirms it instead of retyping it.
* **Unknown** -- nothing to go on. Asked plainly, no option pre-favoured.

Only the confident tier ever suppresses a question; a suggestion never
counts as "resolved" for :attr:`BriefResolution.resolved` (the "Bilinenler"
strip), because it was never actually resolved from anything -- showing a
guess there would misrepresent it as a known fact.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

from app.ai.identity.parties import CounterParty, PartyContext, SelfParty
from app.ai.workflows.correspondence import (
    CORRESPONDENCE_TYPE_LABELS,
    match_genre,
)
from app.ai.workflows.intent_scorer import normalize

#: The "Sen karar ver" sentinel. Never blank: an empty string reads as
#: "unanswered" everywhere a residual-questions check runs, which would
#: re-ask a slot the user explicitly said they don't care about.
AUTO_ANSWER = "__auto__"

#: The brief-gate card never asks more than this many questions in one
#: round, so it can never balloon into an eight-field form. Slots are
#: ordered by ``BriefSlotSpec.priority`` before the cap is applied, so which
#: four is deterministic rather than dict-ordering-dependent.
MAX_BRIEF_QUESTIONS = 4

SlotSource = Literal[
    "user_text", "classification", "document_reply", "prior_brief", "default", "company_profile"
]


@dataclass(frozen=True)
class AnswerOption:
    value: str
    label: str
    description: str = ""


_AUTO_OPTION = AnswerOption(value=AUTO_ANSWER, label="Sen karar ver")


@dataclass(frozen=True)
class SlotResolution:
    value: str
    source: SlotSource
    label: str = ""
    #: False marks a low-confidence guess: the slot is still asked about
    #: (see the module docstring's three-tier split), with this value
    #: offered as the question's suggested option rather than applied
    #: outright.
    confident: bool = True


@dataclass(frozen=True)
class BriefSlotSpec:
    """One writing-style fact the brief either resolves or asks about."""

    key: str
    header: str
    question: str
    options: tuple[AnswerOption, ...] = ()
    multi_select: bool = False
    allow_free_text: bool = True
    required: bool = True
    #: Fixed ordering used both to pick a stable ``MAX_BRIEF_QUESTIONS`` subset
    #: and to render the resolved brief in a predictable order.
    priority: int = 0

    def to_prompt_question(self, suggestion: Optional[SlotResolution] = None) -> dict[str, Any]:
        """Render this slot as a PromptQuestion, folding in a suggestion if any.

        A suggestion whose value matches one of this slot's own catalog
        options (e.g. ``kapanis``'s "arz_ederim") promotes that option to
        the front and marks it recommended, rather than duplicating it. A
        suggestion with no catalog match (a guessed name/institution --
        always ``yazan_taraf``/``muhatap``, the only slots with no fixed
        options at all) is prepended as its own synthetic option instead,
        and the question itself is rewritten as an explicit yes/no
        confirmation ("Önerilen muhatap: Ahmet Yılmaz. Bu doğru mu?")
        rather than the slot's own generic phrasing ("Yazı kime
        gönderilecek?") -- a click on the recommended option should read as
        confirming a specific guess, not answering an open question blind.
        """
        options = list(self.options)
        question_text = self.question
        if suggestion is not None:
            matched_index = next(
                (index for index, option in enumerate(options) if option.value == suggestion.value),
                None,
            )
            if matched_index is not None:
                matched = options[matched_index]
                recommended = AnswerOption(
                    value=matched.value,
                    label=f"{matched.label} (Önerilen)",
                    description=matched.description,
                )
                options = [recommended, *options[:matched_index], *options[matched_index + 1 :]]
            else:
                recommended = AnswerOption(
                    value=suggestion.value,
                    label=f"{suggestion.label or suggestion.value} (Önerilen)",
                    description="Sistemin önerisi",
                )
                options = [recommended, *options]
                # Only for the no-catalog slots (see this method's own
                # docstring) -- a catalog slot's question ("Kapanış ifadesi
                # ne olsun?") already reads fine with a recommended option
                # promoted to the front; it does not name a guessed value
                # that needs confirming the way a bare name/institution does.
                question_text = (
                    f"Önerilen {self.header.lower()}: "
                    f"{suggestion.label or suggestion.value}. Bu doğru mu?"
                )
        # Always present, even for a slot with no catalog options
        # (yazan_taraf/muhatap) -- every slot offers "Sen karar ver".
        options = [*options, _AUTO_OPTION]

        return {
            "key": self.key,
            "question": question_text,
            "header": self.header,
            "help": "",
            "example": suggestion.value if suggestion is not None and not self.options else None,
            "options": [
                {"value": option.value, "label": option.label, "description": option.description}
                for option in options
            ],
            "multi_select": self.multi_select,
            "allow_free_text": self.allow_free_text,
            "required": self.required,
        }


#: The party context a call site that doesn't resolve one (a test, or a
#: caller predating this module's party-awareness) gets by default --
#: `is_known=False`/`relation="none"` on both sides, so every resolver's
#: party-aware branch is a no-op and behaviour falls through to the
#: purely textual heuristics exactly as it did before `PartyContext`
#: existed.
_UNKNOWN_PARTY = PartyContext(us=SelfParty(), them=CounterParty(), relation="none")


@dataclass(frozen=True)
class BriefEvidence:
    raw_text: str
    normalized_text: str
    fields: dict[str, Any]
    prior_brief: dict[str, Any]
    #: Who is writing this letter and who the incoming document (if any)
    #: actually names -- see ``app.ai.identity.parties``. Defaults to an
    #: unknown/neutral context (every resolver's party-aware branch
    #: becomes a no-op) so a caller that never resolved one -- a test, or
    #: any pre-party-model code path -- behaves exactly as it did before
    #: this field existed.
    party: PartyContext = field(default_factory=lambda: _UNKNOWN_PARTY)


@dataclass(frozen=True)
class BriefResolution:
    #: Confidently-resolved slots, keyed by slot key -- what the
    #: "Bilinenler" strip shows. A suggestion never lands here (see the
    #: module docstring): it was never resolved *from* anything, only
    #: guessed, so surfacing it as a known fact would misrepresent it.
    resolved: dict[str, SlotResolution] = field(default_factory=dict)
    #: PromptQuestion-shaped dicts for unresolved slots, priority-ordered and
    #: capped at MAX_BRIEF_QUESTIONS. A slot with a low-confidence guess
    #: still appears here, with the guess folded in as a suggested option.
    questions: tuple[dict[str, Any], ...] = ()


SLOT_CATALOG: tuple[BriefSlotSpec, ...] = (
    #: Priority 0 (lowest number, asked first / never crowded out by the
    #: MAX_BRIEF_QUESTIONS cap) -- getting the correspondence type wrong
    #: shapes the entire draft, unlike a wrong anlatım/kapanış guess which a
    #: revise turn can cheaply correct. See
    #: app.ai.workflows.correspondence.resolve_correspondence_type: this
    #: slot's resolved answer is what "explicit" precedence there refers to.
    BriefSlotSpec(
        key="yazisma_turu",
        header="Yazışma türü",
        question="Nasıl bir yazışma türü hazırlayayım?",
        options=tuple(
            AnswerOption(value=value.value, label=label)
            for value, label in CORRESPONDENCE_TYPE_LABELS.items()
        ),
        priority=0,
    ),
    BriefSlotSpec(
        key="yazan_taraf",
        header="Yazan taraf",
        question="Bu yazıyı kim yazıyor (göndereni)?",
        priority=1,
    ),
    BriefSlotSpec(
        key="muhatap",
        header="Muhatap",
        question="Yazı kime gönderilecek?",
        priority=2,
    ),
    BriefSlotSpec(
        key="anlatim",
        header="Anlatım",
        question="Hangi anlatım biçimini kullanayım?",
        options=(
            AnswerOption("birinci_cogul", "Biz dili", "Ekibimiz/kurumumuz olarak talep ediyoruz"),
            AnswerOption("kurumsal", "Kurumsal dil", "Kurum adına resmî üslup"),
            AnswerOption("birinci_tekil", "Ben dili", "Bireysel dilekçe"),
        ),
        priority=3,
    ),
    BriefSlotSpec(
        key="kapanis",
        header="Kapanış",
        question="Kapanış ifadesi ne olsun?",
        options=(
            AnswerOption("arz_ederim", "Arz ederim", "Üst makama"),
            AnswerOption("rica_ederim", "Rica ederim", "Alt/denk makama"),
            AnswerOption("arz_ve_rica_ederim", "Arz ve rica ederim", ""),
            AnswerOption("bilgilerinize_sunulur", "Bilgilerinize sunulur", "Eşit düzey/bilgi amaçlı"),
        ),
        priority=4,
    ),
    BriefSlotSpec(
        key="imza",
        header="İmza bloğu",
        question="İmza bloğunda ad/unvan yer tutucu mu kalsın?",
        options=(AnswerOption("yer_tutucu", "Yer tutucu bırak", "[Ad Soyad] / [Unvan]"),),
        required=False,
        priority=5,
    ),
    BriefSlotSpec(
        key="sayi",
        header="Sayı",
        # Tarih is deliberately not part of this slot -- it is never asked
        # about at all (see app.ai.workflows.dates.today_tr and
        # draft_graph._build_brief's "0. BUGÜNÜN TARİHİ" section, which
        # fills the writer's own "Tarih:" line automatically).
        question="Sayı alanı nasıl işlensin?",
        options=(
            AnswerOption("yer_tutucu", "Yer tutucu bırak", ""),
            AnswerOption("bos_birak", "Boş bırak", ""),
        ),
        required=False,
        priority=6,
    ),
)

_SLOT_BY_KEY: dict[str, BriefSlotSpec] = {spec.key: spec for spec in SLOT_CATALOG}


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Return the extracted header fields as a plain dict.

    Duplicated from ``draft_graph``/``revise_graph``/``revision.retrieval``
    on purpose -- a shared four-line helper isn't worth a cross-module
    dependency here.
    """
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


#: Collective-noun suffixes that make "<name> <suffix> olarak" read as a
#: self-declaration of who is writing, not a description of the addressee.
_COLLECTIVE_SUFFIX = (
    r"(?:ekibi|ekip|tak[ıi]m[ıi]|tak[ıi]m|kul[uü]b[uü]|kulup|derne[gğ]i|dernek|"
    r"toplulu[gğ]u|topluluk|firmasi|firma|sirketi|sirket|b[oö]l[uü]m[uü]|"
    r"b[oö]l[uü]m|birimi|birim)"
)

#: A candidate name token: must start uppercase (Latin or Turkish), so a
#: run of ordinary lowercase Turkish verbs/connectors before the collective
#: noun ("...dilekçe yazmak istiyoruz KACMAK ekibi olarak") can never be
#: swept into the captured name -- only the actual proper noun can, since
#: Turkish sentence prose is lowercase apart from proper nouns and sentence
#: starts. Bounded to at most 4 tokens so a genuinely multi-word name
#: ("Hacettepe Bilişim Kulübü") still matches whole.
_NAME_TOKEN = r"[A-ZÇĞİÖŞÜ]\w*"

#: Confident: a collective noun ("... ekibi olarak") or an explicit "adına"
#: -- both name the sender unambiguously.
_YAZAN_TARAF_STRONG_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN}\s+(?i:{_COLLECTIVE_SUFFIX}))\s+(?i:olarak)\b"
    ),
    re.compile(rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+(?i:ad[ıi]na)\b"),
)

#: Suggested only: any capitalized phrase directly followed by "olarak",
#: without the collective-noun requirement above -- catches a personal
#: name ("Ahmet Yılmaz olarak") the strong pattern doesn't, but is loose
#: enough (any sentence-initial capital + "olarak") to be worth a guess
#: rather than a silent resolution.
_YAZAN_TARAF_WEAK_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+(?i:olarak)\b"
)

#: Curated institution vocabulary for confidently guessing an addressee.
#: Conservative on purpose -- see the module docstring: no hit falls
#: through to the weak pattern below rather than guessing wrong outright.
_INSTITUTION_VOCABULARY: dict[str, str] = {
    "rektorluk": "Rektörlük",
    "dekanlik": "Dekanlık",
    "valilik": "Valilik",
    "kaymakamlik": "Kaymakamlık",
    "mudurluk": "Müdürlük",
    "bakanlik": "Bakanlık",
    "baskanlik": "Başkanlık",
    "komisyon": "Komisyon",
    "komite": "Komite",
    "genel sekreterlik": "Genel Sekreterlik",
    "teknofest": "TEKNOFEST",
    "tubitak": "TÜBİTAK",
}

#: A capitalized proper noun in the Turkish dative case, apostrophe-marked
#: ("TEKNOFEST'e", "KACMAK'a", "Ahmet Yılmaz'a") -- the orthographic
#: convention for a proper noun taking a case suffix, and a reasonable
#: signal that this is who the letter is addressed to.
_MUHATAP_DATIVE_APOSTROPHE_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN})'(?:e|a|ye|ya|ne|na)\b"
)

#: Same case, without the apostrophe -- a name/institution written the way
#: most people actually type it ("Ahmet Yılmaza", "İnsan Kaynakları
#: Müdürlüğüne"), not the orthographically "correct" apostrophe-marked
#: form. Longest suffix first so "-ne"/"-ya" aren't shadowed by their own
#: trailing "-e"/"-a".
#:
#: Deliberately stops at the two-letter buffer+case forms ("ne"/"na"/"ye"/
#: "ya") rather than also matching the three-letter "üne"/"ına"/"ine"/"una"
#: forms a buffer-consonant analysis would suggest: a Turkish institution
#: name overwhelmingly already ends in its own possessive vowel before the
#: dative attaches ("Müdürlüğü" + "ne" -> "Müdürlüğüne", "Fakültesi" + "ne"
#: -> "Fakültesine") -- stripping the matching two-letter suffix recovers
#: the exact base in that (dominant, in this domain) case. Stripping a
#: three-letter suffix instead would eat into that base vowel too
#: ("Müdürlüğüne" -> "Müdürlüğ", not a word). The trade-off is a stem that
#: itself ends in a bare consonant before an inserted buffer vowel (e.g.
#: "ev" + "ine" -> "evine") comes back one letter too long ("evi", not
#: "ev") -- an acceptable miss for a suggestion-tier heuristic, and not the
#: shape a person/institution name in this domain takes.
_DATIVE_SUFFIXES: tuple[str, ...] = ("ya", "ye", "na", "ne", "a", "e")
_MUHATAP_DATIVE_BARE_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN}(?:{'|'.join(_DATIVE_SUFFIXES)}))\b"
)

#: "Sayın X" -- an explicit salutation naming the addressee outright, the
#: same convention a real official letter's own muhatap line uses.
_MUHATAP_SAYIN_PATTERN = re.compile(
    rf"\bSay[ıi]n\s+((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})"
)

#: "X Bey'e" / "X Hanım'a" -- name plus Turkish honorific plus dative.
#: Captures the honorific too (kept in the display value on purpose, e.g.
#: "Ahmet Bey" -- dropping it would silently downgrade a respectful
#: address the user chose deliberately).
_MUHATAP_HONORIFIC_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN}\s+(?:Bey|Hanım))'(?:e|ne)\b"
)

#: "X için" -- "(a letter/petition) for X" -- a common way to name who a
#: piece of correspondence concerns without any case marking at all.
_MUHATAP_ICIN_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,3}}{_NAME_TOKEN})\s+i[cç]in\b"
)

#: Strips a leading "Sayın " from a candidate value -- "Sayın" itself is a
#: capitalized token and satisfies `_NAME_TOKEN`, so a pattern with no
#: reason to exclude it (`_MUHATAP_ICIN_PATTERN` in particular: "Sayın
#: Ahmet Yılmaz için" reads as one long name-token run ending in "için")
#: would otherwise capture "Sayın Ahmet Yılmaz" as a *different* candidate
#: string than `_MUHATAP_SAYIN_PATTERN`'s own "Ahmet Yılmaz" -- two
#: distinct-looking candidates for what is obviously the same person,
#: which would wrongly downgrade a single-name mention to "ambiguous".
_LEADING_SAYIN_PATTERN = re.compile(r"^Say[ıi]n\s+", re.IGNORECASE)

#: A drafting-request verb stem -- corroborates a single muhatap candidate
#: as confident (see `_resolve_muhatap`): "Ahmet Yılmaz'a bir izin yazısı
#: hazırla" names its addressee unambiguously enough that asking "kime
#: gönderilecek?" back would be redundant, the same way an explicit
#: "X ekibi olarak" already skips asking about yazan_taraf.
_WRITING_VERB_PATTERN = re.compile(r"\b(yaz|hazirla|olustur)\w*\b")

#: Institution keywords that usually sit above the sender in the
#: correspondence hierarchy -- back a weak "Arz ederim" guess for
#: `kapanis` when the resolved/suggested `muhatap` names one of these and
#: neither "arz" nor "rica" was said explicitly.
_AUTHORITY_KEYWORDS = (
    "rektorluk", "dekanlik", "valilik", "kaymakamlik", "bakanlik",
    "baskanlik", "genel mudurluk",
)


def _resolve_yazisma_turu(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    match = match_genre(evidence.raw_text)
    if match is None:
        return None
    correspondence_type, sub_genre = match
    label = sub_genre or CORRESPONDENCE_TYPE_LABELS[correspondence_type]
    return SlotResolution(value=correspondence_type.value, source="user_text", label=label)


def _resolve_yazan_taraf(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    for pattern in _YAZAN_TARAF_STRONG_PATTERNS:
        match = pattern.search(evidence.raw_text)
        if match:
            value = match.group(1).strip(" ,.-")
            if value:
                return SlotResolution(value=value, source="user_text", label=value)

    # A configured company identity is the most reliable signal for who is
    # writing this letter that exists anywhere in the pipeline -- more
    # reliable than a guess derived from the *incoming* document's own
    # header, which is what this fell back to before PartyContext existed
    # (see app.ai.identity.parties's module docstring for the concrete bug
    # that produced: a document's own muhatap treated as our sender
    # unconditionally, with no check that the document was ever actually
    # addressed to us). Ranked above the document-reply fallback below on
    # purpose: an admin-entered identity should win over an inference from
    # document text even when that inference happens to be available too.
    us = evidence.party.us
    if us.is_known:
        value = us.display_name or us.short_name
        if value:
            return SlotResolution(value=value, source="company_profile", label=value)

    # Only reverse the incoming document's own addressee into our sender
    # slot when the document was actually confirmed addressed to us (see
    # resolve_party_context) -- never unconditionally. A document whose
    # muhatap doesn't match our own configured identity (a CV, a
    # third-party report, or one we simply cannot verify) must never
    # donate its addressee to our own antet/imza.
    if evidence.party.relation == "reply_to_us":
        document_muhatap = evidence.fields.get("muhatap")
        if document_muhatap:
            value = str(document_muhatap).strip()
            return SlotResolution(value=value, source="document_reply", label=value)

    weak_match = _YAZAN_TARAF_WEAK_PATTERN.search(evidence.raw_text)
    if weak_match:
        value = weak_match.group(1).strip(" ,.-")
        if value:
            return SlotResolution(value=value, source="user_text", label=value, confident=False)
    return None


def _strip_dative_suffix(phrase: str) -> str:
    """Drop a recognised dative suffix from a matched phrase's last token.

    Only ``_MUHATAP_DATIVE_BARE_PATTERN`` needs this -- every other muhatap
    pattern captures the name without its case ending to begin with (the
    apostrophe/honorific patterns exclude it from the capture group by
    construction, and "Sayın X"/"X için" carry no case suffix at all).

    Args:
        phrase: The full matched phrase, e.g. "Ahmet Yılmaza" or
            "İnsan Kaynakları Müdürlüğüne".

    Returns:
        The phrase with its last token's suffix removed, e.g.
        "Ahmet Yılmaz" / "İnsan Kaynakları Müdürlüğü". Falls back to the
        input unchanged if no listed suffix actually matches (defensive;
        the pattern that produced ``phrase`` already guarantees one does).
    """
    words = phrase.rsplit(" ", 1)
    last = words[-1]
    for suffix in _DATIVE_SUFFIXES:
        if last.lower().endswith(suffix) and len(last) > len(suffix) + 1:
            words[-1] = last[: -len(suffix)]
            return " ".join(words)
    return phrase


def _muhatap_candidates(evidence: BriefEvidence) -> list[str]:
    """Every plausible addressee phrase the user's own text names.

    Order matters only for which candidate is offered as the suggestion
    when there is more than one (the first found); the *count* is what
    decides confidence in ``_resolve_muhatap`` -- a single candidate
    corroborated by a drafting verb is confident, anything else (zero
    candidates aside) is a suggestion to confirm.

    Args:
        evidence: This turn's resolved input.

    Returns:
        Distinct candidate phrases (deduplicated by folded form), in the
        order their patterns were tried.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        value = _LEADING_SAYIN_PATTERN.sub("", raw.strip(" ,.-")).strip()
        if not value:
            return
        folded = normalize(value)
        if folded in seen:
            return
        seen.add(folded)
        candidates.append(value)

    for match in _MUHATAP_SAYIN_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_HONORIFIC_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_DATIVE_APOSTROPHE_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))
    for match in _MUHATAP_DATIVE_BARE_PATTERN.finditer(evidence.raw_text):
        phrase = match.group(1)
        # A *single* capitalized word at the very start of the message is
        # not a reliable name signal -- with no apostrophe, honorific or
        # "Sayın" to disambiguate it, an ordinary sentence-opener that
        # happens to end in a dative-shaped suffix ("Yarışmaya katılmak
        # için...") reads exactly like a genuine bare-dative name
        # otherwise (see `test_a_dative_marked_proper_noun_suggests_the_
        # addressee`'s own note on this same sharp edge for the
        # apostrophe form). A *multi*-word capitalized run in the same
        # position ("Ahmet Yılmaza bir izin yazısı hazırla", "İnsan
        # Kaynakları Müdürlüğüne...") doesn't share that risk -- two or
        # three ordinary words capitalized back to back for no reason is
        # not something Turkish sentences do, position or not -- so only
        # the single-token case is excluded here.
        is_sentence_initial = not evidence.raw_text[: match.start()].strip()
        if is_sentence_initial and len(phrase.split()) == 1:
            continue
        _add(_strip_dative_suffix(phrase))
    for match in _MUHATAP_ICIN_PATTERN.finditer(evidence.raw_text):
        _add(match.group(1))

    return candidates


def _resolve_muhatap(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    # Same guard as _resolve_yazan_taraf's own document-reply branch: only
    # reverse the document's own sender into our addressee slot when the
    # document is confirmed addressed to us. Otherwise this institution
    # belongs to the counterparty and must never become who WE write to.
    if evidence.party.relation == "reply_to_us":
        document_sender = evidence.fields.get("gonderen_kurum")
        if document_sender:
            value = str(document_sender).strip()
            return SlotResolution(value=value, source="document_reply", label=value)
    for surface, label in _INSTITUTION_VOCABULARY.items():
        if re.search(rf"\b{re.escape(surface)}\w*\b", evidence.normalized_text):
            # Our own unit ("İnsan Kaynakları Müdürlüğü" as one of *our*
            # departments) mentioned in the user's own message describes
            # who is writing, never who the letter is addressed to.
            if evidence.party.belongs_to_us(label):
                continue
            return SlotResolution(value=label, source="user_text", label=label)

    candidates = [
        candidate for candidate in _muhatap_candidates(evidence)
        if not evidence.party.belongs_to_us(candidate)
    ]
    if not candidates:
        return None

    value = candidates[0]
    # A single named candidate, said in the same breath as an actual
    # drafting request ("Ahmet Yılmaz'a bir izin yazısı hazırla"), is
    # unambiguous enough to skip the question entirely -- see
    # _WRITING_VERB_PATTERN's own docstring. More than one candidate (the
    # message names two people/institutions) or no drafting verb at all
    # (a passing mention, not clearly a request) stays a suggestion.
    if len(candidates) == 1 and _WRITING_VERB_PATTERN.search(evidence.normalized_text):
        return SlotResolution(value=value, source="user_text", label=value)
    return SlotResolution(value=value, source="user_text", label=value, confident=False)


def _resolve_anlatim(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    if any(pattern.search(evidence.raw_text) for pattern in _YAZAN_TARAF_STRONG_PATTERNS):
        return SlotResolution(value="birinci_cogul", source="user_text", label="Biz dili")
    yazan_taraf = known.get("yazan_taraf")
    if yazan_taraf is not None and yazan_taraf.source == "company_profile":
        # The company itself is resolved as the sender (see
        # _resolve_yazan_taraf) -- the same first-person-plural voice an
        # explicit "... ekibi olarak" gets, since a company writing on its
        # own behalf is exactly that same case, just resolved from its
        # configured identity instead of the message's own wording.
        return SlotResolution(value="birinci_cogul", source="company_profile", label="Biz dili")
    if "dilekce" in evidence.normalized_text and not evidence.fields.get("gonderen_kurum"):
        return SlotResolution(value="birinci_tekil", source="user_text", label="Ben dili")
    # Institutional third-person voice only follows from the document's own
    # sender when the document is confirmed addressed to us -- a
    # third-party document's presence says nothing about our own register.
    if evidence.party.relation == "reply_to_us" and evidence.fields.get("gonderen_kurum"):
        return SlotResolution(value="kurumsal", source="document_reply", label="Kurumsal dil")
    return None


def _resolve_kapanis(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    has_arz = bool(re.search(r"\barz\b", evidence.normalized_text))
    has_rica = bool(re.search(r"\brica\b", evidence.normalized_text))
    if has_arz and has_rica:
        return SlotResolution(
            value="arz_ve_rica_ederim", source="user_text", label="Arz ve rica ederim"
        )
    if has_arz:
        return SlotResolution(value="arz_ederim", source="user_text", label="Arz ederim")
    if has_rica:
        return SlotResolution(value="rica_ederim", source="user_text", label="Rica ederim")

    # No explicit closing word -- fall back to a weak hierarchy guess from
    # whatever muhatap already resolved or was suggested this same pass
    # (kapanis's priority puts it after muhatap, see SLOT_CATALOG).
    muhatap = known.get("muhatap")
    if muhatap and any(
        keyword in normalize(muhatap.value) for keyword in _AUTHORITY_KEYWORDS
    ):
        return SlotResolution(value="arz_ederim", source="user_text", label="Arz ederim", confident=False)
    return None


#: One resolver per slot, tried only when the prior-brief carry-forward
#: (checked first, uniformly, in ``resolve_brief``) didn't already answer
#: it. Absent from this map -- imza/sayi -- means "never inferred,
#: only ever answered by the user or left to Sen karar ver". Each resolver
#: also receives `known`, the slots already settled earlier this same pass
#: (in `SLOT_CATALOG` priority order) -- `kapanis` reads `known["muhatap"]`
#: for its hierarchy guess.
_SLOT_RESOLVERS: dict[
    str, Callable[[BriefEvidence, dict[str, SlotResolution]], Optional[SlotResolution]]
] = {
    "yazisma_turu": _resolve_yazisma_turu,
    "yazan_taraf": _resolve_yazan_taraf,
    "muhatap": _resolve_muhatap,
    "anlatim": _resolve_anlatim,
    "kapanis": _resolve_kapanis,
}


def resolve_brief(
    input_text: str,
    classification: Optional[dict[str, Any]] = None,
    prior_brief: Optional[dict[str, Any]] = None,
    party: Optional[PartyContext] = None,
) -> BriefResolution:
    """Resolve every writing-style slot, asking only about what's unknown.

    Deterministic and LLM-free on purpose: the brief gate is a real
    ``interrupt()`` (see ``app.ai.workflows.planning_graph.brief_gate_node``),
    which replays its own node on resume, and the question set's hash is
    what the frontend dedups the interrupt on -- an unpinned model call in
    this path would make that hash (and the questions themselves)
    non-reproducible across the initial ask and the resume. It also sits
    directly in front of the ~30s draft generation; a second model hop here
    is a visible latency regression for a job a handful of regexes and a
    curated vocabulary already do -- "X ekibi olarak" is a surface pattern,
    not a semantics problem.

    Args:
        input_text: The user's message this turn.
        classification: The document-analysis result, if a document is
            attached. Its ``fields.muhatap``/``fields.gonderen_kurum``
            back the role-inversion rule for a reply-to-a-document turn --
            but only when ``party.relation == "reply_to_us"`` confirms the
            document was actually addressed to us (see
            ``app.ai.identity.parties.resolve_party_context``); a document
            we cannot verify was addressed to us (a CV, a third-party
            report, or simply no self-identity configured to check
            against) never triggers the reversal.
        prior_brief: ``SessionFocus.writing_brief`` from an earlier turn in
            the same session, if any. Every slot it carries is treated as
            already answered, which is what makes turn 2+ of a session
            silent.
        party: This turn's resolved party context (see
            ``app.ai.identity.parties.resolve_party_context``). Defaults to
            an unknown/neutral context -- every party-aware branch below
            becomes a no-op, and resolution falls back to the purely
            textual heuristics that predate this parameter.

    Returns:
        Resolved slots plus the (priority-ordered, capped) list of
        remaining questions -- each carrying a suggested option when a
        resolver had a low-confidence guess for it (see the module
        docstring's three-tier split).
    """
    fields = _coerce_fields(classification or {})
    evidence = BriefEvidence(
        raw_text=input_text or "",
        normalized_text=normalize(input_text or ""),
        fields=fields,
        prior_brief=dict(prior_brief or {}),
        party=party or _UNKNOWN_PARTY,
    )

    resolved: dict[str, SlotResolution] = {}
    suggested: dict[str, SlotResolution] = {}
    #: resolved ∪ suggested, in priority order, so a later resolver
    #: (kapanis) can read an earlier slot's outcome either way.
    known: dict[str, SlotResolution] = {}

    for spec in SLOT_CATALOG:
        prior_value = evidence.prior_brief.get(spec.key)
        if prior_value:
            resolution = SlotResolution(
                value=str(prior_value), source="prior_brief", label=str(prior_value)
            )
            resolved[spec.key] = resolution
            known[spec.key] = resolution
            continue

        resolver = _SLOT_RESOLVERS.get(spec.key)
        resolution = resolver(evidence, known) if resolver else None
        if resolution is not None and resolution.confident:
            resolved[spec.key] = resolution
            known[spec.key] = resolution
        elif resolution is not None:
            suggested[spec.key] = resolution
            known[spec.key] = resolution
        elif not spec.required:
            # An optional slot with nothing to infer defaults straight to
            # "Sen karar ver" instead of competing for one of the
            # MAX_BRIEF_QUESTIONS slots -- required=False means "never
            # worth blocking on", not "ask anyway but let them skip it".
            # Without this, imza/sayi (which have no resolver at
            # all) would always be unresolved and could crowd out a
            # genuinely unknown required slot, or open the gate on a turn
            # where every required fact is already known.
            default = SlotResolution(value=AUTO_ANSWER, source="default", label="Sen karar ver")
            resolved[spec.key] = default
            known[spec.key] = default

    unresolved = sorted(
        (spec for spec in SLOT_CATALOG if spec.key not in resolved),
        key=lambda spec: spec.priority,
    )[:MAX_BRIEF_QUESTIONS]
    questions = tuple(spec.to_prompt_question(suggested.get(spec.key)) for spec in unresolved)

    return BriefResolution(resolved=resolved, questions=questions)


def _display_value(key: str, value: str) -> str:
    """Translate a slug answer (e.g. ``"arz_ederim"``) to its Turkish label.

    Free-text answers (a name, an institution typed by hand) have no
    matching option and are returned unchanged.
    """
    spec = _SLOT_BY_KEY.get(key)
    if spec is None:
        return value
    for option in spec.options:
        if option.value == value:
            return option.label
    return value


def format_writing_brief(answers: dict[str, str]) -> str:
    """Render the resolved writing brief for the writer's grounding prompt.

    Every slot the writer needs a direction for is stated explicitly,
    including a slot answered ``AUTO_ANSWER`` -- omitting an unknown slot
    reads to the model as "no constraint", which is the exact failure mode
    this module exists to close (see the module docstring).

    Args:
        answers: Final slot values -- resolved automatically, supplied by
            the human at the brief gate, or ``AUTO_ANSWER``.

    Returns:
        The brief section's Turkish text, or an explanatory placeholder if
        no answers were supplied at all (a document-less, gate-disabled
        turn where nothing tried to resolve anything).
    """
    if not answers:
        return "Yazım briefi oluşturulmadı; taslak dili genel resmî üslupla yazılmalıdır."

    lines: list[str] = []
    for spec in SLOT_CATALOG:
        value = answers.get(spec.key)
        if not value:
            continue
        if value == AUTO_ANSWER:
            lines.append(f"- {spec.header}: (sistem karar verecek)")
            continue
        display = _display_value(spec.key, value)
        if spec.key == "yazan_taraf":
            lines.append(
                f"- Yazıyı Yazan Taraf (gönderen): {display}\n"
                "  → Bu ad ANTET ve İMZA BLOĞUNDA yer alır. Muhatap satırında ASLA yer almaz."
            )
        elif spec.key == "muhatap":
            lines.append(
                f"- Yazının Gönderileceği Makam (muhatap): {display}\n"
                "  → Bu ad YALNIZCA muhatap satırında yer alır."
            )
        else:
            lines.append(f"- {spec.header}: {display}")

    return "\n".join(lines) if lines else format_writing_brief({})
