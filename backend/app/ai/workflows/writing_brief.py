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
  a document's own header field). Never asked about at all.
* **Suggested** -- a weaker signal (a bare capitalized phrase, an inferred
  hierarchy guess) worth surfacing, but not worth silently trusting. Still
  asked about, but the guess rides along as the question's first option,
  labelled "(Önerilen)" -- a click confirms it instead of retyping it.
* **Unknown** -- nothing to go on. Asked plainly, no option pre-favoured.

Only the confident tier ever suppresses a question; a suggestion never
counts as "resolved" for :attr:`BriefResolution.resolved` (the "Bilinenler"
strip), because it was never actually resolved from anything -- showing a
guess there would misrepresent it as a known fact.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional

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

SlotSource = Literal["user_text", "classification", "document_reply", "prior_brief", "default"]


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
        suggestion with no catalog match (a guessed name/institution) is
        prepended as its own synthetic option instead.
        """
        options = list(self.options)
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
        # Always present, even for a slot with no catalog options
        # (yazan_taraf/muhatap) -- every slot offers "Sen karar ver".
        options = [*options, _AUTO_OPTION]

        return {
            "key": self.key,
            "question": self.question,
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


@dataclass(frozen=True)
class BriefEvidence:
    raw_text: str
    normalized_text: str
    fields: dict[str, Any]
    prior_brief: dict[str, Any]


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
        key="sayi_tarih",
        header="Sayı ve tarih",
        question="Sayı/tarih alanı nasıl işlensin?",
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

#: Suggested only: a capitalized proper noun in the Turkish dative case,
#: apostrophe-marked ("TEKNOFEST'e", "KACMAK'a") -- the orthographic
#: convention for a proper noun taking a case suffix, and a reasonable
#: (not certain) signal that this is who the letter is addressed to.
_MUHATAP_WEAK_PATTERN = re.compile(
    rf"((?:{_NAME_TOKEN}\s+){{0,2}}{_NAME_TOKEN})'(?:e|a|ye|ya|ne|na)\b"
)

#: Institution keywords that usually sit above the sender in the
#: correspondence hierarchy -- back a weak "Arz ederim" guess for
#: `kapanis` when the resolved/suggested `muhatap` names one of these and
#: neither "arz" nor "rica" was said explicitly.
_AUTHORITY_KEYWORDS = (
    "rektorluk", "dekanlik", "valilik", "kaymakamlik", "bakanlik",
    "baskanlik", "genel mudurluk",
)


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


def _resolve_muhatap(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    document_sender = evidence.fields.get("gonderen_kurum")
    if document_sender:
        value = str(document_sender).strip()
        return SlotResolution(value=value, source="document_reply", label=value)
    for surface, label in _INSTITUTION_VOCABULARY.items():
        if re.search(rf"\b{re.escape(surface)}\w*\b", evidence.normalized_text):
            return SlotResolution(value=label, source="user_text", label=label)
    weak_match = _MUHATAP_WEAK_PATTERN.search(evidence.raw_text)
    if weak_match:
        value = weak_match.group(1).strip(" ,.-")
        if value:
            return SlotResolution(value=value, source="user_text", label=value, confident=False)
    return None


def _resolve_anlatim(
    evidence: BriefEvidence, known: dict[str, SlotResolution]
) -> Optional[SlotResolution]:
    del known
    if any(pattern.search(evidence.raw_text) for pattern in _YAZAN_TARAF_STRONG_PATTERNS):
        return SlotResolution(value="birinci_cogul", source="user_text", label="Biz dili")
    if "dilekce" in evidence.normalized_text and not evidence.fields.get("gonderen_kurum"):
        return SlotResolution(value="birinci_tekil", source="user_text", label="Ben dili")
    if evidence.fields.get("gonderen_kurum"):
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
#: it. Absent from this map -- imza/sayi_tarih -- means "never inferred,
#: only ever answered by the user or left to Sen karar ver". Each resolver
#: also receives `known`, the slots already settled earlier this same pass
#: (in `SLOT_CATALOG` priority order) -- `kapanis` reads `known["muhatap"]`
#: for its hierarchy guess.
_SLOT_RESOLVERS: dict[
    str, Callable[[BriefEvidence, dict[str, SlotResolution]], Optional[SlotResolution]]
] = {
    "yazan_taraf": _resolve_yazan_taraf,
    "muhatap": _resolve_muhatap,
    "anlatim": _resolve_anlatim,
    "kapanis": _resolve_kapanis,
}


def resolve_brief(
    input_text: str,
    classification: Optional[dict[str, Any]] = None,
    prior_brief: Optional[dict[str, Any]] = None,
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
            back the role-inversion rule for a reply-to-a-document turn.
        prior_brief: ``SessionFocus.writing_brief`` from an earlier turn in
            the same session, if any. Every slot it carries is treated as
            already answered, which is what makes turn 2+ of a session
            silent.

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
            # Without this, imza/sayi_tarih (which have no resolver at
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
