"""Deterministic register and consistency checks a regex can decide alone.

``draft_verifier.py`` answers "is every concrete claim grounded and is the
structure complete" -- set-membership questions. This module answers a
different, narrower class of question that doesn't need an LLM either, just a
different kind of pattern match: "does this draft address the same person
consistently," "does it repeat itself instead of saying something new," and
"did the signature block get filled with the placeholder's own label instead
of a real value." All three are concrete, regex-checkable symptoms of the
reported bug's "gövde dolgu paragraflarıyla doldu" and "imza bloğu uydurma"
failure shapes, kept separate from ``draft_verifier`` the same way
``app.ai.identity.parties`` is: this module imports from ``draft_verifier``
(the same one-directional dependency ``llm_judge.py`` and ``parties.py``
already use), never the reverse, so ``draft_verifier`` stays a leaf module.

Findings are plain ``RuleFinding``s (see ``confidence_rules.py``) -- the
caller (``draft_graph.verify_node``) folds them into the same
``merge_verdicts`` pass that already scores PII/mevzuat/judge findings and
turns them into ``repair_items`` for the existing verify -> revise -> writer
loop. No new detection surface is added here beyond what that loop already
knows how to act on.
"""

import re

from app.ai.verification.confidence_rules import RuleFinding
from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, _fold, _signature_block

#: A person referred to with the formal third-person address form used for
#: the addressee ("Sayın Ahmet Yılmaz"). Two to three capitalized tokens
#: after "Sayın" -- a name, not an institution (an institution's own antet
#: line never starts with "Sayın").
_SAYIN_PATTERN = re.compile(
    r"\bSayın\s+([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*(?:\s+[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*){0,2})"
)

#: The same person referred to with an informal honorific instead ("Ahmet
#: Bey'in", "Ayşe Hanım"). Case suffixes ("'nin", "'in", ...) are optional so
#: both the bare and the possessive-inflected form match.
_BEY_HANIM_PATTERN = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*(?:\s+[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*){0,2})\s+"
    r"(?:Bey|Hanım)(?:'(?:nin|nın|nün|nun|in|ın|ün|un))?\b"
)


def check_person_consistency(draft: str) -> list[RuleFinding]:
    """Flag the same named person addressed two different, conflicting ways.

    A well-formed draft refers to any one person by exactly one register
    throughout -- the formal "Sayın X" form for the addressee, or the
    informal "X Bey/Hanım" form for someone mentioned in passing. The same
    name appearing under both forms means the draft lost track of who it
    was talking about (the reported bug's shape: the addressee institution
    treated as a person, or a third party addressed as if they were reading
    the letter).

    Args:
        draft: The generated draft text.

    Returns:
        One ``kisi_tutarsizligi`` finding per name caught in both forms.
    """
    sayin_token_sets = [
        set(_fold(name).split()) for name in _SAYIN_PATTERN.findall(draft) if _fold(name)
    ]
    if not sayin_token_sets:
        return []

    findings: list[RuleFinding] = []
    seen: set[str] = set()
    for match in _BEY_HANIM_PATTERN.finditer(draft):
        folded = _fold(match.group(1))
        tokens = set(folded.split())
        # A subset match, not exact equality: "Sayın Ahmet Yılmaz" (full
        # name) and "Ahmet Bey" (first name only) are the ordinary way the
        # same person is written in each register -- requiring the full
        # folded string to match exactly would miss precisely that pairing.
        is_same_person = tokens and any(tokens <= sayin_tokens for sayin_tokens in sayin_token_sets)
        if is_same_person and folded not in seen:
            seen.add(folded)
            findings.append(
                RuleFinding(
                    rule_id="kisi_tutarsizligi",
                    detail=(
                        f"'{match.group(1)}' hem 'Sayın' hitabıyla hem "
                        "'Bey/Hanım' hitabıyla geçiyor -- aynı kişi için tek bir "
                        "hitap biçimi kullanılmalı."
                    ),
                )
            )
    return findings


#: A sentence boundary -- period/exclamation/question mark followed by
#: whitespace, or any run of newlines. The newline alternative keeps a
#: header line ("Konu: ...") from gluing onto the body's first sentence
#: when there's no punctuation between them, which would otherwise make
#: that sentence's *first* occurrence textually different from its later,
#: unprefixed repeats and hide the very repetition this function looks for.
#: Not abbreviation-aware ("T.C." splits into two pieces), which is harmless
#: here: a fragment too short to carry six significant tokens is skipped
#: below regardless of why it's short.
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")

#: Sentences shorter than this many significant tokens are exempt -- a short
#: repeated fragment ("Bilgilerinize sunulur.") is very likely a legitimate,
#: intentionally formulaic closing, not padding. Padding is a *content-free
#: sentence restated*, and a genuine restatement of a full idea is long
#: enough to have this many tokens by construction.
_MIN_FILLER_TOKENS = 6


def check_filler_sentences(draft: str) -> list[RuleFinding]:
    """Flag a substantial sentence that repeats verbatim elsewhere in the draft.

    A well-formed official letter never states the same full idea twice --
    each paragraph carries a new fact or step. A repeated sentence is, by
    construction, one that added nothing new the second time: the "gövde
    dolgu paragraflarıyla doldu" symptom the reported bug produced, without
    needing a curated list of "generic-sounding" phrases (which would be
    both incomplete and prone to flagging legitimate formulaic Turkish
    official register).

    Args:
        draft: The generated draft text.

    Returns:
        One ``dolgu_ifade`` finding per distinct sentence that recurs.
    """
    stripped = PLACEHOLDER_PATTERN.sub(" ", draft)
    sentences = [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(stripped) if s.strip()]

    counts: dict[str, tuple[int, str]] = {}
    for sentence in sentences:
        folded = _fold(sentence)
        if len(folded.split()) < _MIN_FILLER_TOKENS:
            continue
        occurrences, sample = counts.get(folded, (0, sentence))
        counts[folded] = (occurrences + 1, sample)

    return [
        RuleFinding(
            rule_id="dolgu_ifade",
            detail=f"Tekrarlanan cümle ({occurrences}x): '{sample}'",
        )
        for occurrences, sample in counts.values()
        if occurrences > 1
    ]


#: A self-referential meta-commentary sentence -- the model narrating its
#: own review scope ("sadece verilen kayıt incelenmiştir") instead of
#: grounding the sentence to a concrete, named request/document/mevzuat.
#: Deliberately narrow (only the "yalnızca/sadece ... incelenmiştir" shape
#: this bug report's symptom took), not a general hedging-language filter --
#: a broader match would flag legitimate, concrete uses of the same verbs
#: ("Talebiniz incelenmiştir.", grounded to "talebiniz").
_META_COMMENTARY_PATTERN = re.compile(
    r"\b(?:sadece|yalnızca)\s+(?:verilen|sağlanan|sunulan|elde\s+edilen)"
    r"(?:\s+\S+){1,3}\s+(?:incelenmiştir|değerlendirilmiştir|dikkate\s+alınmıştır)",
    re.IGNORECASE,
)


def check_meta_commentary(draft: str) -> list[RuleFinding]:
    """Flag process narration about the model's own review scope.

    See ``_META_COMMENTARY_PATTERN``'s own docstring for why the match is
    kept this narrow.

    Args:
        draft: The generated draft text.

    Returns:
        One ``meta_yorum`` finding per match.
    """
    return [
        RuleFinding(rule_id="meta_yorum", detail=f"Süreç üst-yorumu: '{match.group(0)}'")
        for match in _META_COMMENTARY_PATTERN.finditer(draft)
    ]


#: A signature-block line whose *entire* folded content is one of the
#: placeholder's own bare labels -- the model wrote the label as if it were
#: the value instead of either filling it in or leaving the bracketed
#: placeholder ``normalize_role_placeholders`` already knows how to attribute
#: and route to the human gate. Same label set as
#: ``placeholders._SIGNATURE_PLACEHOLDERS``'s keys, duplicated rather than
#: imported: that map is keyed for the *bracketed* case and lives in a module
#: that itself imports from ``draft_verifier``, so importing it here as well
#: would add a second edge into the same leaf module for no benefit -- the
#: two lists only need to agree on content, not share an import.
_BARE_META_SIGNATURE_VALUES = frozenset(
    _fold(label)
    for label in (
        "Ad Soyad", "Ad, Soyad", "Adı Soyadı", "Soyad", "Unvan", "Ünvan",
        "İmza", "İmza Sahibi", "Kişi Adı", "Yetkili",
    )
)


def check_signature_block(draft: str) -> list[RuleFinding]:
    """Flag a signature-block line that is a bare placeholder label, unbracketed.

    ``normalize_role_placeholders`` (see ``placeholders.py``) already
    attributes a bracketed ``[Ad Soyad]``/``[Unvan]`` to whoever it belongs
    to. This catches the case that backstop cannot see at all: the model
    writes the label's own words as if they were the filled-in value --
    "Ad Soyad" or "Yetkili" on its own line, no brackets -- which reads to
    every downstream check as a (fabricated, meaningless) real name.

    Args:
        draft: The generated draft text.

    Returns:
        One ``imza_blogu_uydurma`` finding per bare meta-value line found.
    """
    block = _signature_block(draft)
    findings: list[RuleFinding] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or PLACEHOLDER_PATTERN.search(stripped):
            continue
        if _fold(stripped) in _BARE_META_SIGNATURE_VALUES:
            findings.append(
                RuleFinding(
                    rule_id="imza_blogu_uydurma",
                    detail=(
                        f"İmza bloğunda '{stripped}' yer tutucu etiketi, gerçek bir "
                        "değer gibi çıplak (köşeli parantezsiz) yazılmış."
                    ),
                )
            )
    return findings
