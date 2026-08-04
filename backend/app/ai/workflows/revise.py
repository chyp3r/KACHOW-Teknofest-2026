"""The revise flow: a targeted, deterministic-first edit to the active draft.

Unlike ``draft_graph`` (classify -> write -> verify -> reflexion loop),
revise never re-classifies and never re-retrieves legislation -- it operates
directly on ``SessionFocus.active_draft``, the text the user already saw and
is asking to change. Six steps, one of them an LLM call::

    1. Parse the instruction        deterministic  (parse_revision_instruction)
    2. Locate the target section    deterministic  (locate_target)
    3. Rewrite the target            1 LLM call     (run_revise)
    4. Merge back into the draft    deterministic  (_merge)
    5. Verify                       deterministic + conditional judge
    6. Version                      handled by SessionFocus.compute_focus_update,
                                     not here -- see planning_graph.focus_node

Step 4's merge is a plain character splice: ``source[:start] + rewritten +
source[end:]``. Because the untouched head and tail come straight from the
original text rather than being reproduced by the model, there is no way
for the rewrite to silently drift outside its target span -- the "did the
model change something it shouldn't have" risk a full-draft reflexion loop
has to check for is structurally impossible here, not merely checked after
the fact.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Optional

from langchain_core.runnables import RunnableConfig

from app.ai.agents.judge import JudgeAgent
from app.ai.agents.reviser import ReviserAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.llms.base import BaseLLMClient
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.session.focus import DraftVersion
from app.ai.verification import (
    InfoQuestion,
    build_missing_info_request,
    judge_draft,
    merge_verdicts,
    verify_draft,
)
from app.ai.workflows.correspondence import format_correspondence_profile
from app.ai.workflows.intent_scorer import normalize
from app.core.config import settings
from app.core.enums.step_status import StepStatus

logger = logging.getLogger(__name__)

Scope = Literal["paragraph", "section", "whole"]
Operation = Literal["tone_formal", "tone_informal", "shorten", "lengthen", "content"]


@dataclass(frozen=True)
class RevisionInstruction:
    """The user's revise request, parsed into a scope and an operation.

    Attributes:
        scope: What part of the draft the instruction targets.
        operation: What kind of change it asks for. Informational only --
            it does not change which prompt runs, only what a caller might
            log or show; the model reads ``raw`` directly.
        section_hint: A recognized structural part name (see
            ``_SECTION_HINTS``), when ``scope == "section"``.
        ordinal: A 1-based paragraph index (``-1`` means "last"), when
            ``scope == "paragraph"``.
        raw: The instruction text, unmodified, for the prompt.
    """

    scope: Scope
    operation: Operation
    section_hint: Optional[str]
    ordinal: Optional[int]
    raw: str


@dataclass(frozen=True)
class TargetSpan:
    """A char range in the draft the rewrite should be confined to."""

    start: int
    end: int
    text: str


#: Recognized structural parts of the fixed 9-part official letter format
#: (see prompts/templates/writer.md) and the phrases that name them.
_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "konu": ("konu",),
    "giris": ("giris", "ilk paragraf", "baslangic paragrafi"),
    "kapanis": ("kapanis", "son paragraf", "arz kismi", "rica kismi"),
    "imza": ("imza", "imza blogu", "imza kismi"),
}

#: Phrases inside the *closing* paragraph specifically -- used to locate the
#: "kapanış" section structurally rather than just by position, since a
#: closing sentence can appear mid-paragraph rather than alone on one.
_CLOSING_MARKERS = ("arz ederim", "rica ederim", "bilgilerinize sunulur")

_ORDINAL_PATTERN = re.compile(r"(\d+)\s*\.?\s*paragraf")
_ORDINAL_WORDS: dict[str, int] = {
    "ilk": 1, "birinci": 1, "ikinci": 2, "ucuncu": 3, "dorduncu": 4, "son": -1,
}

_OPERATION_HINTS: dict[Operation, tuple[str, ...]] = {
    "tone_formal": ("daha resmi", "resmiyet"),
    "tone_informal": ("daha samimi", "daha sicak"),
    "shorten": ("kisalt", "daha kisa", "ozetle"),
    "lengthen": ("uzat", "daha uzun", "detaylandir", "genislet"),
}


def parse_revision_instruction(instruction: str) -> RevisionInstruction:
    """Extract a scope and an operation from a revise request.

    Deterministic keyword matching over the draft's own known, fixed
    structure -- not a general NLU parse. An instruction naming neither a
    paragraph number nor a recognized section resolves to ``scope="whole"``,
    which is the safe default: a full, still single-call rewrite rather than
    a guess at which part was meant.

    Args:
        instruction: The user's revise request.

    Returns:
        The parsed instruction.
    """
    normalized = normalize(instruction)

    section_hint: Optional[str] = None
    for canonical, surfaces in _SECTION_HINTS.items():
        if any(surface in normalized for surface in surfaces):
            section_hint = canonical
            break

    ordinal: Optional[int] = None
    match = _ORDINAL_PATTERN.search(normalized)
    if match:
        ordinal = int(match.group(1))
    else:
        padded = f" {normalized} "
        for word, value in _ORDINAL_WORDS.items():
            if f" {word} paragraf" in padded:
                ordinal = value
                break

    operation: Operation = "content"
    for op, surfaces in _OPERATION_HINTS.items():
        if any(surface in normalized for surface in surfaces):
            operation = op
            break

    if ordinal is not None:
        scope: Scope = "paragraph"
    elif section_hint is not None:
        scope = "section"
    else:
        scope = "whole"

    return RevisionInstruction(
        scope=scope, operation=operation, section_hint=section_hint,
        ordinal=ordinal, raw=instruction,
    )


def _split_paragraphs(draft: str) -> list[tuple[int, int]]:
    """Return (start, end) char offsets of each blank-line-separated paragraph."""
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", draft)]


def locate_target(draft: str, instruction: RevisionInstruction) -> Optional[TargetSpan]:
    """Find the char span ``instruction`` targets, if it names one precisely.

    Args:
        draft: The current draft text.
        instruction: The parsed instruction.

    Returns:
        The target span, or ``None`` when the scope is ``"whole"`` or the
        named paragraph/section can't be located -- callers treat ``None``
        as "rewrite the whole draft" rather than guessing.
    """
    paragraphs = _split_paragraphs(draft)
    if not paragraphs:
        return None

    if instruction.scope == "paragraph" and instruction.ordinal is not None:
        index = instruction.ordinal - 1 if instruction.ordinal > 0 else len(paragraphs) - 1
        if 0 <= index < len(paragraphs):
            start, end = paragraphs[index]
            return TargetSpan(start, end, draft[start:end])
        return None

    if instruction.scope == "section" and instruction.section_hint:
        if instruction.section_hint == "imza":
            start, end = paragraphs[-1]
            return TargetSpan(start, end, draft[start:end])
        if instruction.section_hint == "kapanis":
            for start, end in paragraphs:
                if any(marker in normalize(draft[start:end]) for marker in _CLOSING_MARKERS):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if instruction.section_hint == "konu":
            for start, end in paragraphs:
                if normalize(draft[start:end]).startswith("konu"):
                    return TargetSpan(start, end, draft[start:end])
            return None
        if instruction.section_hint == "giris":
            start, end = paragraphs[0]
            return TargetSpan(start, end, draft[start:end])

    return None


def _build_revise_prompt(
    *,
    source_draft: str,
    target: Optional[TargetSpan],
    instruction: RevisionInstruction,
    brief: str,
    correspondence_type: str,
) -> str:
    """Compose the reviser's prompt, scoped to the target span when one was found."""
    if target is not None:
        scope_rule = (
            f"### DEĞİŞTİRİLECEK BÖLÜM (yalnızca bunu yeniden yaz):\n{target.text}\n\n"
            "### KURAL:\nYalnızca yukarıdaki bölümü, aşağıdaki kullanıcı talimatına göre "
            "yeniden yaz. Taslağın geri kalanından hiçbir şey isteme veya tekrarlama; "
            "SADECE bu bölümün yeni halini döndür."
        )
    else:
        scope_rule = (
            "### KURAL:\nAşağıdaki kullanıcı talimatına göre TÜM taslağı yeniden yaz. "
            "Brief'te olmayan hiçbir yeni bilgi (kişi, kurum, tarih, sayı, mevzuat maddesi) "
            "ekleme; yalnızca istenen üslup/kapsam/uzunluk değişikliğini yap."
        )

    return (
        "### GÖREV:\n"
        "Kullanıcı, mevcut bir resmî yazı taslağında hedefli bir değişiklik istiyor.\n\n"
        f"### BRIEF BELGESİ:\n{brief}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n{format_correspondence_profile(correspondence_type)}\n\n"
        f"### MEVCUT TASLAK:\n{source_draft}\n\n"
        f"{scope_rule}\n\n"
        f"### KULLANICI TALİMATI:\n{instruction.raw}\n\n"
        "### ÇIKTI:\nYalnızca istenen bölümün (veya kural tüm taslağı kapsıyorsa taslağın "
        "tamamının) yeni metnini döndür. Meta yorum, markdown kod bloğu veya açıklama ekleme."
    )


def _merge(source_draft: str, target: Optional[TargetSpan], rewritten: str) -> str:
    """Splice the rewritten text back in. See module docstring for why this
    makes an unintended change to the untouched portion structurally
    impossible rather than merely something to check for afterward."""
    rewritten = rewritten.strip()
    if target is None:
        return rewritten
    return f"{source_draft[:target.start]}{rewritten}{source_draft[target.end:]}"


async def run_revise(
    *,
    active_draft: DraftVersion,
    instructions: str,
    correspondence_type: str,
    llm_client: BaseLLMClient,
    fast_llm_client: Optional[BaseLLMClient],
    reasoning_level: str,
    config: Optional[RunnableConfig] = None,
    emit_token_fn=None,
) -> dict[str, Any]:
    """Produce a targeted revision of the active draft.

    Returns a dict shaped like ``draft_graph``'s own output (``status``,
    ``draft``, ``correspondence_type``, ``confidence_score``,
    ``combined_score``, ``verification``, ``judge``, ``missing_information``,
    ``requires_human_approval``, ``classification``, ``context``,
    ``source_document``) so downstream code -- ``human_gate_node``,
    ``_step_routing``, and ``focus_node``'s versioning -- treats a revised
    draft uniformly with a freshly generated one.

    Args:
        active_draft: The draft version being revised, carrying its own
            grounding (``classification``/``context``/``source_document``)
            forward from when it was written.
        instructions: The user's revise request, unparsed.
        correspondence_type: Falls back to ``active_draft``'s own type when
            the caller has nothing more specific (there is nothing to
            re-resolve here -- revise never re-classifies).
        llm_client: Quality-tier client.
        fast_llm_client: Fast-tier client, used for the optional judge. Falls
            back to ``llm_client`` when omitted, same as draft_graph.
        reasoning_level: Selects the judge's on/off default the same way
            draft_graph's reflexion loop does.
        config: Runnable config, forwarded to ``emit_token_fn``.
        emit_token_fn: Optional ``async (config, node, chunk) -> None``,
            called per streamed chunk so the frontend can show the rewrite
            live, the same way draft_graph's writer does. Omitted in tests
            that don't care about streaming.

    Returns:
        The revision result.
    """
    instruction = parse_revision_instruction(instructions)
    target = locate_target(active_draft.text, instruction)

    brief = (
        f"1. Önceki Taslak Sürümü: {active_draft.version}\n"
        f"2. Doğrulanmış Sınıflandırma: {active_draft.classification.get('summary', 'Özet yok.')}\n"
        f'3. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{active_draft.context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
    )
    resolved_correspondence_type = correspondence_type or active_draft.correspondence_type

    preset = get_reasoning_level_preset(reasoning_level)
    agent = ReviserAgent(fast_llm_client if preset.model_tier == "fast" and fast_llm_client else llm_client)
    prompt = _build_revise_prompt(
        source_draft=active_draft.text,
        target=target,
        instruction=instruction,
        brief=brief,
        correspondence_type=resolved_correspondence_type,
    )

    chunks: list[str] = []
    try:
        async for chunk in agent.stream(
            messages=prompt, temperature=0.2, max_tokens=preset.draft_max_tokens,
            reasoning=preset.reasoning,
        ):
            chunks.append(chunk)
            if emit_token_fn is not None:
                await emit_token_fn(config, "revise", chunk)
    except Exception as exc:
        logger.exception("Revise step failed to generate a rewrite")
        return {
            "draft": active_draft.text,
            "correspondence_type": resolved_correspondence_type,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": f"Revizyon üretilemedi: {exc}",
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
        }

    rewritten = "".join(chunks).strip()
    if not rewritten:
        return {
            "draft": active_draft.text,
            "correspondence_type": resolved_correspondence_type,
            "confidence_score": 0.0,
            "combined_score": 0.0,
            "requires_human_approval": True,
            "status": StepStatus.FAILED,
            "error": "Ajan boş bir revizyon döndürdü.",
            "classification": active_draft.classification,
            "context": active_draft.context,
            "source_document": active_draft.source_document,
        }

    assert_no_prompt_leak(rewritten)
    merged_draft = _merge(active_draft.text, target, rewritten)

    report = verify_draft(
        merged_draft,
        source_document=active_draft.source_document,
        context=active_draft.context,
        classification=active_draft.classification,
        instructions=instructions,
        strict=resolved_correspondence_type != "other_official",
    )

    judge_on = settings.DRAFT_JUDGE_ENABLED if preset.judge_enabled is None else preset.judge_enabled
    verdict = None
    if judge_on:
        judge_agent = JudgeAgent(fast_llm_client or llm_client)
        verdict = await judge_draft(
            judge_agent,
            draft=merged_draft,
            brief=brief,
            correspondence_type=resolved_correspondence_type,
            instructions=instructions,
            timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
        )

    missing_information: list[InfoQuestion] = []
    if report.placeholder_count > 0:
        missing_information = build_missing_info_request(
            merged_draft, report, active_draft.classification
        )

    combined = merge_verdicts(report, verdict, missing_information=missing_information)
    requires_approval = combined.requires_human_approval or not active_draft.context

    if missing_information:
        status = StepStatus.NEEDS_INPUT
    elif requires_approval:
        status = StepStatus.NEEDS_HUMAN_APPROVAL
    else:
        status = StepStatus.COMPLETED

    return {
        "draft": merged_draft,
        "correspondence_type": resolved_correspondence_type,
        "confidence_score": combined.combined_score,
        "combined_score": combined.combined_score,
        "requires_human_approval": requires_approval,
        "evaluation_notes": combined.notes,
        "verification": report.model_dump(),
        "judge": verdict.model_dump() if verdict is not None else {},
        "judge_available": combined.judge_available,
        "repair_items": [item.model_dump() for item in combined.repair_items],
        "missing_information": [q.model_dump() for q in missing_information],
        "status": status,
        "classification": active_draft.classification,
        "context": active_draft.context,
        "source_document": active_draft.source_document,
        "reasoning_level": preset.level.value,
    }
