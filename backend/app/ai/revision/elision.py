"""Detects a reviser response that elided or dropped real content instead of
reproducing it verbatim.

``app.ai.workflows.revise_graph``'s module docstring states a "structural
no-drift guarantee": untouched text is never reproduced by the model. That
guarantee only actually holds on the multi-directive path, where each
rewrite is spliced back with ``app.ai.revision.instruction._merge`` against
the original draft. Two other paths hand the model's raw output through
unspliced:

* A whole-draft rewrite, when the instruction's target span couldn't be
  located (``rewrite_node``'s ``target is None`` branch).
* Every repair-loop pass (``rewrite_node``'s ``is_repair`` branch) -- the
  reviser is asked to reproduce the whole previous draft, fixing only the
  listed defects.

Both prompts tell the model to preserve what it wasn't asked to change, but
neither the prompt nor anything downstream previously checked that it
actually did. A smaller/faster model asked to "reproduce the rest verbatim"
is a well-known setup for lazily standing in an ellipsis or a bracketed note
for a paragraph it judged unchanged -- silently deleting real content the
user (or an earlier turn) had already filled in.

This module is the deterministic check that catches it, in the same shape
as ``app.ai.verification.draft_verifier``'s other checks: free, reproducible,
regex/length-based, feeding a ``RepairItem`` into the existing bounded
repair loop rather than inventing a second one.
"""

import re
from dataclasses import dataclass
from typing import Optional

from app.ai.workflows.intent_scorer import normalize

#: A model regenerating a whole draft sometimes takes a shortcut for a
#: section it judges "unchanged" -- an ellipsis, or a bracketed/parenthesized
#: note standing in for real content -- instead of reproducing it. Official
#: Turkish correspondence never legitimately contains any of these (they are
#: distinct from the system's own ``[BİLGİ EKSİK: ...]`` missing-information
#: placeholder syntax, which names what's missing rather than gesturing at
#: "the rest"), so a hit is unambiguous evidence of elision, not a false
#: positive to guard against.
_ELISION_MARKERS = re.compile(
    r"(\.{3,}|…|"
    r"\[(?:de[gğ]i[sş]medi|ayn[ıi]|i[cç]erik ayn[ıi]|de[gğ]i[sş]iklik yok)\]|"
    r"\((?:de[gğ]i[sş]medi|ayn[ıi]|i[cç]erik ayn[ıi] kald[ıi]|k[ıi]salt[ıi]ld[ıi])\))",
    re.IGNORECASE,
)

#: Instruction keywords that legitimately ask for a shorter draft -- a big
#: length drop under one of these is the user's own request, not content
#: loss. Includes explicit deletion/removal verbs ("sil", "cikar",
#: "kaldir") alongside the length/summary ones: a "şu paragraftan bir kısmı
#: sil" request that the reviser actually honoured must never be flagged as
#: an elision defect and looped back into a repair pass whose own prompt
#: tells the model to restore "already-filled" content -- that would
#: silently undo the very deletion the user asked for.
_SHORTENING_KEYWORDS = (
    "kisalt", "ozetle", "sadelestir", "daha kisa", "kucult", "sil", "cikar", "kaldir",
)

#: Below this fraction of the previous draft's length, with no shortening
#: instruction in play, a rewrite is presumed to have silently dropped
#: content rather than genuinely have had that little left to say.
_MIN_LENGTH_RATIO = 0.6


@dataclass(frozen=True)
class ContentLossFinding:
    detail: str
    suggested_fix: str


def detect_content_loss(
    previous_draft: str, rewritten_draft: str, instructions: str
) -> Optional[ContentLossFinding]:
    """Flag a rewrite that likely dropped real content instead of only
    applying the requested change.

    Args:
        previous_draft: The draft text before this rewrite pass (the
            active draft on a fresh revise turn, or the last attempt's
            output on a repair pass).
        rewritten_draft: The model's new output for this pass.
        instructions: The user's revision instruction, checked for an
            explicit request to shorten before the length-ratio check fires.

    Returns:
        A finding describing what looks lost, or ``None`` when nothing does.
    """
    markers = _ELISION_MARKERS.findall(rewritten_draft)
    if markers:
        return ContentLossFinding(
            detail=(
                "Taslakta önceki içeriğin yerine kısaltma/atlama ifadesi "
                f"({', '.join(sorted(set(markers)))}) kullanılmış."
            ),
            suggested_fix=(
                "Talimatla ilgisiz her cümleyi önceki taslaktaki haliyle, "
                "kelimesi kelimesine ve eksiksiz olarak yeniden üret; hiçbir "
                "kısmı '...' veya benzeri bir ifadeyle atlama."
            ),
        )

    previous_length = len(previous_draft.strip())
    if previous_length == 0:
        return None
    rewritten_length = len(rewritten_draft.strip())
    wants_shorter = any(
        keyword in normalize(instructions) for keyword in _SHORTENING_KEYWORDS
    )
    if not wants_shorter and rewritten_length < previous_length * _MIN_LENGTH_RATIO:
        percentage = round(rewritten_length / previous_length * 100)
        return ContentLossFinding(
            detail=(
                "Revize edilen taslak, talimatta kısaltma istenmediği halde "
                f"önceki taslağın yaklaşık %{percentage}'i uzunluğunda -- içerik "
                "kaybı olabilir."
            ),
            suggested_fix=(
                "Talimatla ilgisiz olan tüm cümle ve paragrafları önceki "
                "taslaktaki haliyle, eksiksiz olarak koru; yalnızca istenen "
                "değişikliği uygula."
            ),
        )
    return None
