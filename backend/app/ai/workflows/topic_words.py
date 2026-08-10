"""Shared "does this instruction carry topic content of its own" helper.

Both ``app.ai.workflows.scope`` (does a message need an anchor at all) and
``app.ai.workflows.relevance`` (does a document-attached request concern
*this* document) need the same building block: strip the drafting/revision
command itself out of a message and see what -- if anything -- is left. A
bare "Cevap yaz." is definitionally in-domain (it asks the system to do
exactly what it exists to do, with nothing further to be *about*); "Cevap
yaz, çiğköfte kampanyası için" is not, because "çiğköfte kampanyası"
survives the strip. Factored out once so the two modules can't quietly
diverge on what counts as a command versus a topic.
"""

from app.ai.workflows.intent_rules import CONTINUATION_SURFACES, DRAFT_RULES, REVISE_RULES
from app.ai.workflows.intent_scorer import normalize

__all__ = ["content_words"]

#: Command/structural surfaces stripped out before judging whether a message
#: carries any topic content beyond the request itself -- pulled from the
#: same evidence tables the router already scores drafting/revision
#: requests against (``intent_rules.DRAFT_RULES``/``REVISE_RULES``'s own
#: ``explicit_request``/``arrange_request`` entries), plus
#: ``CONTINUATION_SURFACES`` ("evet", "devam et", ...): a short affirmative
#: confirming the previous turn carries no topic of its own by definition,
#: it only ever refers to whatever the prior turn already established.
#: Pulling from the router's own tables rather than a second,
#: independently-maintained phrase list keeps the two from drifting apart.
_COMMAND_SURFACES: frozenset[str] = frozenset(
    (
        *(
            surface
            for rule in (*DRAFT_RULES, *REVISE_RULES)
            if rule.id.endswith(("explicit_request", "arrange_request"))
            for surface in rule.surfaces
        ),
        *CONTINUATION_SURFACES,
    )
)

#: `_COMMAND_SURFACES` sorted longest-first. `content_words` strips surfaces
#: by sequential substring replacement, and a short surface that is also a
#: substring of a longer one ("hazirla" inside "yazi hazirla") would
#: otherwise get its turn first and fragment the longer phrase -- leaving
#: "yazi hazirla" with "hazirla" already gone, so the 2-word surface never
#: matches and "yazi" wrongly survives as if it were topic content. Longest
#: first guarantees a multi-word command is always removed whole before any
#: of its own single-word pieces are considered separately.
_COMMAND_SURFACES_BY_LENGTH: tuple[str, ...] = tuple(
    sorted(_COMMAND_SURFACES, key=len, reverse=True)
)

#: Function words and the bare verbs already covered by ``_COMMAND_SURFACES``
#: as multi-word phrases -- excluded again here as single tokens so e.g.
#: "taslağı hazırla" (not in the phrase list verbatim, but "hazirla" alone)
#: doesn't get counted as topic content.
_STOPWORDS: frozenset[str] = frozenset(
    (
        "bir bu su o ve veya ile icin gibi da de ki mi mu musun misin "
        "lutfen rica ederim olur musunuz yaz yazar yazin taslak metin "
        "cevap cevabi hazirla hazirlar hazirlayin olustur olusturur "
        "cikar cikarir kaleme al alin uret uretir"
    ).split()
)

#: Shortest word length that counts as potential topic content. Below this,
#: Turkish function words and suffix-only fragments dominate.
_MIN_CONTENT_WORD_LENGTH = 4


def content_words(message: str) -> set[str]:
    """Words in ``message`` that are neither a drafting command nor filler.

    Args:
        message: Raw (not yet normalised) user text.

    Returns:
        The remaining significant words, normalised. Empty when the message
        is nothing but the command itself.
    """
    stripped = normalize(message)
    for surface in _COMMAND_SURFACES_BY_LENGTH:
        stripped = stripped.replace(surface, " ")
    return {
        word
        for word in stripped.split()
        if len(word) >= _MIN_CONTENT_WORD_LENGTH and word not in _STOPWORDS
    }
