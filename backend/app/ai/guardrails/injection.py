"""Prompt-injection scrubbing at the document-text and generation boundaries.

OCR'd or directly extracted document text flows into agent prompts with no
sanitisation. A submitted PDF is attacker-controlled input from the system's
perspective -- anyone who can get a document in front of an employee can put
text in it, including text shaped like an instruction to whichever model
processes it ("önceki talimatları unut", "you are now..."). This module is
the boundary check, applied once right after extraction (before the
``char_count`` gate runs, so a scrubbed document is what actually gets
measured) rather than repeated ad hoc at every prompt call site.

Deterministic and regex-based, matching the rest of this codebase's
verification layer (``draft_verifier.py``, ``planner.py``): a classifier would
need training data and adds a model call to a path that runs on every upload.
"""

import re
import unicodedata

_TURKISH_MAP = str.maketrans(
    {
        "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "İ": "i",
        "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u",
    }
)


class GuardrailViolation(Exception):
    """Raised when a generated response looks like it leaked the system
    prompt or obeyed embedded instructions instead of doing its actual job."""


#: Zero-width and bidi control characters (U+200B-U+200F, U+202A-U+202E,
#: U+FEFF), used to hide text from a casual read while still being tokenised
#: by the model.
_INVISIBLE_CHARS = re.compile(
    "[​‌‍‎‏‪-‮﻿]"
)

#: Turkish and English instruction-override patterns, matched against folded
#: (lowercased, diacritic-stripped) text so casing and Turkish characters
#: can't be used to dodge the match.
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bonceki\s+talimatlar\w*\s+(unut|yoksay|dikkate\s+alma)\w*",
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\bdisregard\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\bsen\s+artik\b",
        r"\byou\s+are\s+now\b",
        r"^\s*system\s*:",
        r"^\s*###?\s*(system|sistem)\b",
        r"\bact\s+as\s+(a|an)\b",
        r"\byapay\s+zeka\s+asistani\s+degil",
    )
)


def _fold(text: str) -> str:
    """Fold Turkish text to lowercase ASCII for pattern matching."""
    translated = (text or "").translate(_TURKISH_MAP)
    normalized = unicodedata.normalize("NFKD", translated)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def scrub_extracted_text(text: str) -> tuple[str, list[str]]:
    """Strip invisible characters and instruction-override lines from extracted text.

    Removing a line is a deliberate, coarse choice: partial redaction inside a
    line risks leaving a truncated instruction that still parses as one, and
    document text is line-oriented enough (header fields, one clause per
    line) that dropping a whole line rarely costs real content.

    Args:
        text: Raw extracted/OCR'd document text.

    Returns:
        The cleaned text, and a list of short Turkish markers describing what
        was removed -- surfaced on the analysis response
        (``extraction.scrubbed_markers``) so cleaning is reported, not silent.
    """
    if not text:
        return text, []

    markers: list[str] = []
    cleaned = _INVISIBLE_CHARS.sub("", text)
    if cleaned != text:
        markers.append("gizli_karakterler_temizlendi")

    kept_lines: list[str] = []
    removed = 0
    for line in cleaned.split("\n"):
        if any(pattern.search(_fold(line)) for pattern in _INJECTION_PATTERNS):
            removed += 1
            continue
        kept_lines.append(line)

    if removed:
        markers.append(f"olasi_talimat_enjeksiyonu_{removed}_satir_kaldirildi")

    return "\n".join(kept_lines), markers


#: This app's own prompt-scaffold section headers -- the numbered brief
#: markers (``_build_brief`` in ``app.ai.workflows.revise_graph``/
#: ``draft_graph``), the writer/reviser prompt's own section headings
#: ("### GÖREV", "### BRIEF BELGESİ", ...). A smaller local model
#: occasionally echoes fragments of its own instructions back as if they
#: were content, especially under a heavily-numbered prompt like the revise
#: repair prompt -- distinct from ``_INJECTION_PATTERNS`` above, which
#: catches a user *trying* to hijack the model, not the model regurgitating
#: its own scaffolding unprompted. Matched narrowly against this
#: application's own literal section labels rather than a generic "looks
#: like a prompt" heuristic, so a legitimate draft that happens to discuss
#: e.g. "görev tanımı" in its own official prose is never caught by it.
_SCAFFOLD_ECHO_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"###\s*(gorev|brief\s+belgesi|yazisma\s+turu\s+profili|degistirilecek\s+bolum|"
        r"mevcut\s+taslak|kullanici\s+talimati|kural|cikti|onceki\s+taslak)\b",
        r"\bbrief\s+belgesi\s*:",
        r"\bonceki\s+taslak\s+surumu\s*:",
        r"\bdogrulanmis\s+siniflandirma\s*:",
        r"\bdogrulanmis\s+mevzuat\s+baglami\s*:",
        r"\byazisma\s+turu\s+profili\s*:",
        r"\buslup\s+referans\s+ornekleri\s*:",
        r"\bnumarali\s+kusur\s+listesindeki\b",
    )
)


def assert_no_scaffold_echo(response: str) -> None:
    """Validator: raise if a generated response echoes this app's own
    prompt-scaffold headers (the numbered brief, the writer/reviser
    prompt's section markers) instead of producing plain draft prose.

    Wired into the revise flow's ``rewrite_node`` (see
    ``app.ai.workflows.revise_graph``), which builds prompts around a
    heavily-structured numbered brief -- exactly the shape a smaller local
    model is most prone to imitating in its own completion.

    Args:
        response: The agent's generated text.

    Raises:
        GuardrailViolation: If a scaffold-echo pattern is detected.
    """
    folded = _fold(response or "")
    for pattern in _SCAFFOLD_ECHO_PATTERNS:
        if pattern.search(folded):
            raise GuardrailViolation(
                "Üretilen yanıt, talimat şablonunun kendisini (brief/prompt "
                "iskeleti) içeriyor -- gerçek bir taslak metni değil."
            )


def assert_no_prompt_leak(response: str) -> None:
    """Validator: raise if a generated response echoes an override instruction
    or reads like a system-prompt leak rather than the agent's actual output.

    Wired into ``BaseAgent.validators`` for the writer/reviser/classifier
    agents (see ``app/ai/agents/base.py``); a violation fails the current
    attempt rather than being silently returned to the user.

    Args:
        response: The agent's generated text.

    Raises:
        GuardrailViolation: If a leak pattern is detected.
    """
    folded = _fold(response or "")
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(folded):
            raise GuardrailViolation(
                "Üretilen yanıt olası bir talimat enjeksiyonu veya sistem "
                "promptu sızıntısı içeriyor."
            )
