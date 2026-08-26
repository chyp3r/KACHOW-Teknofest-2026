"""Bir regex'in tek başına karar verebileceği deterministik kayıt/üslup ve
tutarlılık kontrolleri.

``draft_verifier.py`` "her somut iddia dayanaklı mı ve yapı tam mı" sorusunu
yanıtlar -- küme-üyeliği soruları. Bu modül, bir LLM de gerektirmeyen, farklı
bir tür örüntü eşleştirmesi gerektiren farklı, daha dar bir soru sınıfını
yanıtlar: "bu taslak aynı kişiye tutarlı bir şekilde hitap ediyor mu," "yeni
bir şey söylemek yerine kendini tekrar ediyor mu" ve "imza bloğu gerçek bir
değer yerine yer tutucunun kendi etiketiyle mi dolduruldu." Üçü de, bildirilen
hatanın "gövde dolgu paragraflarıyla doldu" ve "imza bloğu uydurma" hata
şekillerinin somut, regex ile kontrol edilebilir belirtileridir;
``app.ai.identity.parties``'in olduğu gibi ``draft_verifier``'dan ayrı
tutulur: bu modül ``draft_verifier``'dan içe aktarır (``llm_judge.py`` ve
``parties.py``'nin zaten kullandığı aynı tek yönlü bağımlılık), asla tersi
değil, böylece ``draft_verifier`` bir yaprak modül olarak kalır.

Bulgular düz ``RuleFinding``lardır (bkz. ``confidence_rules.py``) --
çağıran (``draft_graph.verify_node``), bunları zaten PII/mevzuat/yargıç
bulgularını skorlayan ve mevcut doğrula -> revize et -> yazar döngüsü için
``repair_items``e dönüştüren aynı ``merge_verdicts`` geçişine katlar. Burada
o döngünün zaten üzerine hareket etmeyi bildiğinin ötesinde yeni bir tespit
yüzeyi eklenmez.
"""

import re

from app.ai.verification.confidence_rules import RuleFinding
from app.ai.verification.draft_verifier import PLACEHOLDER_PATTERN, _fold, _signature_block

#: Muhatap için kullanılan resmi üçüncü şahıs hitap biçimiyle atıfta
#: bulunulan bir kişi ("Sayın Ahmet Yılmaz"). "Sayın"dan sonra iki ila üç
#: büyük harfle başlayan token -- bir isim, bir kurum değil (bir kurumun
#: kendi antet satırı asla "Sayın" ile başlamaz).
_SAYIN_PATTERN = re.compile(
    r"\bSayın\s+([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*(?:\s+[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*){0,2})"
)

#: Aynı kişiye bunun yerine gayri resmi bir unvanla atıfta bulunuluyor
#: ("Ahmet Bey'in", "Ayşe Hanım"). Hâl ekleri ("'nin", "'in", ...) isteğe
#: bağlıdır, böylece hem çıplak hem de iyelik ekli biçim eşleşir.
_BEY_HANIM_PATTERN = re.compile(
    r"\b([A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*(?:\s+[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ']*){0,2})\s+"
    r"(?:Bey|Hanım)(?:'(?:nin|nın|nün|nun|in|ın|ün|un))?\b"
)


def check_person_consistency(draft: str) -> list[RuleFinding]:
    """Aynı adlandırılmış kişiye iki farklı, çelişen şekilde hitap edilmesini işaretle.

    İyi biçimlendirilmiş bir taslak, herhangi bir kişiye baştan sona tam
    olarak tek bir kayıtla atıfta bulunur -- muhatap için resmi "Sayın X"
    biçimi veya geçerken bahsedilen biri için gayri resmi "X Bey/Hanım"
    biçimi. Aynı adın her iki biçimde de görünmesi, taslağın kimden
    bahsettiğini kaybettiği anlamına gelir (bildirilen hatanın şekli:
    muhatap kurumun bir kişi gibi ele alınması veya üçüncü bir tarafa
    sanki mektubu okuyorlarmış gibi hitap edilmesi).

    Args:
        draft: Üretilen taslak metni.

    Returns:
        Her iki biçimde de yakalanan her isim için bir
        ``kisi_tutarsizligi`` bulgusu.
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
