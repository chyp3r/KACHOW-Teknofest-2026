import asyncio
import json
import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.ai.agents.judge import JudgeAgent
from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.guardrails.injection import assert_no_prompt_leak
from app.ai.guardrails.pii import find_pii
from app.ai.policy import get_policy
from app.ai.policy.budget import node_budget
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.examples import ExampleRetriever
from app.ai.verification import (
    DraftJudgeVerdict,
    InfoQuestion,
    build_missing_info_request,
    judge_draft,
    merge_verdicts,
    verify_draft,
)
from app.ai.workflows.correspondence import (
    format_correspondence_profile,
    resolve_correspondence_type,
)
from app.ai.workflows.events import (
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_token,
)
from app.ai.workflows.resilience import IO_RETRY
from app.ai.reasoning_levels import ReasoningLevelPreset, get_reasoning_level_preset
from app.core.config import settings
from app.core.enums.reasoning_level import ReasoningLevel
from app.observability.ai_metrics import DRAFT_REVISIONS, DRAFT_SCORE, LLM_TOKENS

logger = logging.getLogger(__name__)

#: The "balanced" reasoning-level preset carries today's pre-existing
#: defaults verbatim (see app.ai.reasoning_levels), so deriving these two
#: constants from it -- rather than duplicating the literals -- makes
#: "balanced reproduces today's behaviour exactly" a structural guarantee
#: instead of something that can drift out of sync.
_BALANCED_PRESET = get_reasoning_level_preset(ReasoningLevel.BALANCED)

#: Generation budget for a draft. An official letter with header, body and
#: signature block runs 600-1200 tokens; the old global cap of 1024 truncated
#: the longer ones mid-sentence.
DRAFT_MAX_TOKENS = _BALANCED_PRESET.draft_max_tokens

#: One initial generation plus at most one revision. Each attempt is a full
#: local generation (~25-30s); a third attempt would blow the ~90s draft
#: latency budget and rarely succeeds where the second one didn't. The
#: "deep" reasoning level raises this bound for callers willing to trade
#: latency for another repair pass -- see app.ai.reasoning_levels.
MAX_DRAFT_ATTEMPTS = _BALANCED_PRESET.max_draft_attempts


class DraftState(TypedDict, total=False):
    """LangGraph state for the drafting workflow."""

    source_document: str
    classification: dict[str, Any]
    correspondence_type: str
    correspondence_type_source: str
    context: str
    instructions: str
    draft: str
    previous_draft: str
    confidence_score: float
    combined_score: float
    requires_human_approval: bool
    requires_revision: bool
    evaluation_notes: str
    verification: dict[str, Any]
    judge: dict[str, Any]
    judge_available: bool
    repair_items: list[dict[str, Any]]
    pii_findings: list[dict[str, Any]]
    missing_information: list[dict[str, Any]]
    attempt_history: list[dict[str, Any]]
    status: str
    error: str
    attempts: int
    brief: str
    #: Speed-vs-quality tier for this run ("fast"/"balanced"/"deep"); see
    #: app.ai.reasoning_levels.get_reasoning_level_preset. Absent or unknown
    #: resolves to "balanced", so older callers that never set it are
    #: unaffected.
    reasoning_level: str
    #: Few-shot style examples retrieved for this draft (see
    #: retrieve_examples_node), each a plain dict with "text",
    #: "correspondence_type", "niyet", "kurum", "baslik". Set once before the
    #: first writer pass and left untouched by revise_node, so a repair
    #: attempt sees the same examples as the original draft rather than
    #: re-querying. Empty (never absent) when retrieval is disabled, finds
    #: nothing, or fails -- few-shot is a quality boost, not a dependency.
    style_examples: list[dict[str, Any]]


def _format_classification(classification: dict[str, Any]) -> str:
    """Serialize analysis output for grounded agent prompts.

    Args:
        classification: The analysis result, which may contain LangChain
            Documents and Pydantic models alongside plain values.

    Returns:
        Pretty-printed JSON, or a repr when the structure resists serialization.
    """
    if not classification:
        return "Sınıflandırma bilgisi sağlanmadı."

    def _clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _clean(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_clean(item) for item in value]
        if hasattr(value, "page_content") and hasattr(value, "metadata"):
            return {"page_content": value.page_content, "metadata": value.metadata}
        if hasattr(value, "model_dump"):
            return _clean(value.model_dump())
        return value

    cleaned = _clean(classification)
    try:
        return json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    except Exception:
        return str(cleaned)


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    """Return the extracted header fields as a plain dict."""
    fields = classification.get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_brief(
    classification: dict[str, Any], context: str, instructions: str
) -> str:
    """Compose the grounding brief handed to the writer.

    Args:
        classification: Analysis output for the incoming document.
        context: Retrieved legislation excerpts.
        instructions: The user's drafting instructions.

    Returns:
        The brief text.
    """
    fields = _coerce_fields(classification)
    missing = classification.get("missing_fields") or []
    missing_labels = ", ".join(
        item.get("label", "") for item in missing if isinstance(item, dict)
    )

    return (
        f"1. Belge Türü: "
        f"{classification.get('document_type_label') or classification.get('document_type') or 'Belirtilmedi'}\n"
        f"2. Belge Özeti: {classification.get('summary') or 'Özet çıkarılamadı.'}\n"
        f"3. Çıkarılan Kritik Bilgiler:\n"
        f"   - Tarih: {fields.get('tarih') or 'Bulunamadı'}\n"
        f"   - Sayı: {fields.get('sayi') or 'Bulunamadı'}\n"
        f"   - Konu: {fields.get('konu') or 'Bulunamadı'}\n"
        f"   - Muhatap: {fields.get('muhatap') or 'Bulunamadı'}\n"
        f"   - Gönderen Kurum: {fields.get('gonderen_kurum') or 'Bulunamadı'}\n"
        f"   - İmza Sahibi: {fields.get('imza_sahibi') or 'Bulunamadı'}"
        f" ({fields.get('imza_unvani') or 'unvan yok'})\n"
        f"4. Evrakta Tespit Edilen Eksik Alanlar: {missing_labels or 'yok'}\n"
        f'5. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
        f"6. Kullanıcı Talebi ve Talimatlar: {instructions}\n"
    )


def _build_repair_prompt(state: DraftState) -> str:
    """Compose the targeted repair prompt handed to the reviser.

    Sends the full brief rather than a defect-conditional slice of it. The
    brief is already a condensed representation (a few thousand characters at
    most -- the writer never sees the raw ``source_document`` either, only
    this brief), so brief + previous draft + defect list stays comfortably
    inside the model's context window with room to spare for the output.

    Args:
        state: Current draft state, expected to carry ``previous_draft`` and
            ``repair_items`` from the preceding verify/revise pass.

    Returns:
        The repair prompt.
    """
    defects = state.get("repair_items") or []
    numbered = "\n".join(
        f"{index}. [{item.get('kind')}] {item.get('detail')}"
        + (f" -> Öneri: {item.get('suggested_fix')}" if item.get("suggested_fix") else "")
        for index, item in enumerate(defects, start=1)
    )

    return (
        "### GÖREV:\n"
        "Aşağıdaki önceki taslağı, YALNIZCA numaralı kusur listesindeki maddeleri "
        "gidererek düzelt. Listede olmayan hiçbir cümleyi değiştirme.\n\n"
        f"### BRIEF BELGESİ:\n{state.get('brief', '')}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n"
        f"{format_correspondence_profile(state.get('correspondence_type', 'other_official'))}\n\n"
        f"### ÖNCEKİ TASLAK:\n{state.get('previous_draft', '')}\n\n"
        f"### DÜZELTİLMESİ GEREKEN KUSURLAR:\n{numbered or '(kusur listesi boş)'}\n\n"
        "### KURAL:\n"
        "Yalnızca listelenen kusurları düzelt. Başka hiçbir cümleyi değiştirme. "
        "`[...]` yer tutucularını olduğu gibi bırak."
        f"{_format_style_examples(state.get('style_examples'))}"
    )


def _format_style_examples(style_examples: list[dict[str, Any]] | None) -> str:
    """Render retrieved few-shot style examples as a prompt block.

    Returns "" (not an empty section) when there are none -- an "### ÜSLUP
    REFERANS ÖRNEKLERİ" header with nothing under it would read to the model
    as a missing-context signal, not as "no examples were retrieved this
    time".

    The examples are real letters pulled from
    ``datasets/resmi_yazisma/ornekler.jsonl`` via ``ExampleRetriever`` --
    genuine institution names, dates and case numbers, not synthetic
    placeholders. The block explicitly tells the model they are a style
    reference only, never a source of fact, and the boundary is enforced a
    second time downstream by ``draft_verifier``'s ``ornek_sizintisi`` check
    (deterministic, not prompt-only) precisely because a prompt instruction
    alone is not a guarantee.
    """
    if not style_examples:
        return ""

    blocks = "\n".join(
        f'<ornek tur="{example.get("correspondence_type", "")}" '
        f'niyet="{example.get("niyet", "")}">\n'
        f'{example.get("text", "")}\n'
        "</ornek>"
        for example in style_examples
    )

    return (
        "\n\n### ÜSLUP REFERANS ÖRNEKLERİ:\n"
        "Aşağıdaki metinler gerçek resmî yazılardan alınmış ÜSLUP VE YAPI örnekleridir. "
        "Bunlar brief'in bir parçası DEĞİLDİR ve doğrulanmış bilgi kaynağı DEĞİLDİR.\n\n"
        f"{blocks}\n\n"
        "KURAL (KRİTİK): Örneklerden YALNIZCA biçimi öğren -- alan sıralaması, ilgi satırı "
        "kalıbı, paragraf ritmi, kapanış ve imza bloğu düzeni, resmî üslup. Örneklerdeki "
        "hiçbir kurum adı, kişi adı, tarih, sayı, mevzuat atfı, tutar veya olayı taslağa "
        "TAŞIMA. Taslaktaki her somut bilgi yalnızca BRIEF BELGESİ'nden gelmelidir."
    )


def _resolve_free_text_client(
    preset: ReasoningLevelPreset,
    llm_client: BaseLLMClient,
    fast_llm_client: BaseLLMClient | None,
) -> BaseLLMClient:
    """Pick the client that backs writer/reviser generation for a run.

    Module-level (rather than a closure inside ``create_draft_graph``) so it
    can be unit-tested and reasoned about independently of the compiled graph.
    Never introduces a third client: only ``fast_llm_client`` or
    ``llm_client``, the same two already handed to ``create_draft_graph``.
    """
    if preset.model_tier == "fast" and fast_llm_client is not None:
        return fast_llm_client
    return llm_client


def create_draft_graph(
    llm_client: BaseLLMClient,
    fast_llm_client: BaseLLMClient | None = None,
    example_retriever: ExampleRetriever | None = None,
):
    """Create and compile the drafting workflow.

    Flow::

        START -> validate_input -+-> retrieve_examples -> writer -+-> verify -+-> revise -> writer
                                  \\-> END                          \\-> END     |-> END (needs_input)
                                                                                 \\-> END

    The former single-pass "writer -> LLM editor" pipeline had no path back to
    the writer, so a low-scoring draft was only ever flagged, never repaired.
    ``verify`` now runs a hybrid gate -- the deterministic ``verify_draft``
    plus a fast-tier judge for what regex cannot see (request fit, arz/rica
    direction, register, muhatap consistency) -- and routes to a bounded
    ``revise -> writer`` loop when the defects found are the kind a targeted
    text edit can actually fix. Defects that aren't (an explicit placeholder
    the writer left because it doesn't know the value; a guessed
    correspondence type) go straight to human review or an information
    request instead of being retried into the same gap.

    Args:
        llm_client: The quality-tier LLM used by the writer and reviser.
        fast_llm_client: Optional fast-tier client for the judge. Falls back
            to ``llm_client`` when omitted.
        example_retriever: Optional few-shot style-example retriever (see
            ``retrieve_examples_node``). None reproduces pre-feature
            behaviour exactly -- the node short-circuits to zero examples
            without touching Qdrant.

    Returns:
        The compiled LangGraph workflow.
    """
    # Writer/reviser are *not* built once here: which client backs them
    # depends on the reasoning level of the run in progress (see writer_node),
    # so a fresh, cheap agent wrapper is constructed per call instead. The
    # judge always uses the fast tier regardless of level -- only whether it
    # runs at all varies (see verify_node) -- so it stays a single instance.
    judge_agent = JudgeAgent(fast_llm_client or llm_client)

    async def validate_input_node(state: DraftState) -> dict[str, Any]:
        classification = state.get("classification") or {}
        instructions = (
            (state.get("instructions") or "").strip()
            or "Gelen evraka uygun resmî ve kurumsal bir yazışma taslağı oluştur."
        )
        correspondence_type, type_source = resolve_correspondence_type(
            state.get("correspondence_type"), instructions, classification
        )

        source_document = (state.get("source_document") or "").strip()
        if not source_document:
            error = "Gelen evrak içeriği sağlanmadığı için taslak oluşturulamadı."
            logger.error(error)
            return {
                "correspondence_type": correspondence_type.value,
                "correspondence_type_source": type_source,
                "draft": "",
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": error,
                "attempts": state.get("attempts", 0),
                "brief": "",
            }

        context = (state.get("context") or "").strip()
        return {
            "source_document": source_document,
            "classification": classification,
            "correspondence_type": correspondence_type.value,
            "correspondence_type_source": type_source,
            "context": context,
            "instructions": instructions,
            "brief": _build_brief(classification, context, instructions),
            "status": "IN_PROGRESS",
            "error": "",
            "attempts": state.get("attempts", 0),
        }

    def route_after_validation(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "retrieve_examples"

    async def retrieve_examples_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        """Fetch few-shot style examples for the writer's first pass.

        Runs once per draft, before the writer/revise loop -- not inside
        ``node_timeout``'s decorator, deliberately: that decorator lets a
        timeout propagate out of the node and crash the whole graph run (see
        ``writer_node``'s own note on why it avoids it too), which is the
        opposite of what an optional quality boost should do on a slow
        Qdrant. The budget is still enforced, just with an inline
        ``asyncio.timeout`` whose failure path degrades to zero examples
        instead.
        """
        await emit_node_start(
            config,
            "examples",
            "Üslup Örnekleri",
            "Benzer resmî yazı örnekleri aranıyor...",
        )

        policy = get_policy().draft
        if example_retriever is None or not policy.style_examples_enabled:
            await emit_node_skipped(
                config, "examples", "Üslup Örnekleri", "Örnek getirimi devre dışı."
            )
            return {"style_examples": []}

        classification = state.get("classification") or {}
        fields = _coerce_fields(classification)
        query = " ".join(
            part
            for part in (
                fields.get("konu") or "",
                classification.get("summary") or "",
                state.get("instructions") or "",
            )
            if part
        ).strip()
        correspondence_type = state.get("correspondence_type") or "other_official"

        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        budget = node_budget("retrieve_examples", preset.level)
        try:
            async with asyncio.timeout(budget):
                examples = await example_retriever.retrieve(
                    query=query,
                    correspondence_type=correspondence_type,
                    limit=policy.style_example_count,
                    char_budget=policy.style_example_char_budget,
                )
        except Exception:
            # ExampleRetriever.retrieve never raises on its own (it degrades
            # to []) -- the only thing this can catch is the asyncio.timeout
            # above firing. Caught broadly anyway so a future change to the
            # retriever can't turn an optional lookup into a failed draft.
            logger.exception("Style example retrieval failed; continuing without examples.")
            await emit_node_error(
                config,
                "examples",
                "Üslup Örnekleri",
                "Örnek getirimi başarısız; taslak örneksiz devam ediyor.",
                fatal=False,
            )
            return {"style_examples": []}

        style_examples = [
            {
                "text": example.text,
                "correspondence_type": example.correspondence_type,
                "niyet": example.niyet,
                "kurum": example.kurum,
                "baslik": example.baslik,
            }
            for example in examples
        ]
        await emit_node_end(
            config,
            "examples",
            "Üslup Örnekleri",
            f"{len(style_examples)} üslup örneği bulundu."
            if style_examples
            else "Uygun üslup örneği bulunamadı.",
            {"style_examples": style_examples},
        )
        return {"style_examples": style_examples}

    async def writer_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        attempt_number = state.get("attempts", 0) + 1
        is_revision = bool(state.get("previous_draft"))
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        client = _resolve_free_text_client(preset, llm_client, fast_llm_client)
        meta = {
            "attempt": attempt_number,
            "reasoning_level": preset.level.value,
            "reasoning": preset.reasoning,
        }

        if is_revision:
            logger.info("Running Reviser Node (attempt %d)...", attempt_number)
            await emit_node_start(
                config,
                "draft",
                "Taslak Revizyonu",
                f"[Revizyon Ajanı] Taslak {attempt_number}. denemede düzeltiliyor...",
                meta=meta,
            )
            agent = ReviserAgent(client)
            prompt = _build_repair_prompt(state)
            temperature = 0.2
        else:
            logger.info("Running Writer Node...")
            await emit_node_start(
                config,
                "draft",
                "Taslak Oluşturma",
                "[Yazar Ajanı] Taslak yazılıyor...",
                meta=meta,
            )

            is_other = state.get("correspondence_type") == "other_official"
            if is_other:
                rules = (
                    "- Yazışma türü 'Diğer resmî yazışma' olduğu için, brief'te bulunmayan "
                    "tamamlayıcı bilgileri genel kurumsal bilgi birikiminle tamamlayabilirsin.\n"
                    "- Resmî yazı standartlarına uygunluğu sağlamak için makul tamamlamalar yapabilirsin."
                )
            else:
                rules = (
                    "- Yalnızca brief içindeki bilgilere ve mevzuat bağlamına sadık kal.\n"
                    "- Gelen evrakta veya mevzuatta yer almayan hiçbir kişi, kurum, sayı, "
                    "tarih veya olay uydurma.\n"
                    "- Zorunlu olup brief'te bulunmayan bilgileri köşeli parantezli yer "
                    "tutucu olarak bırak (örn. '[Tarih Eksik - Lütfen Doldurun]')."
                )

            prompt = (
                "### GÖREV:\n"
                "Aşağıdaki brief doğrultusunda resmî ve kurumsal bir Türkçe yazı taslağı yaz.\n\n"
                f"### BRIEF BELGESİ:\n{state['brief']}\n\n"
                f"### YAZIŞMA TÜRÜ PROFİLİ:\n"
                f"{format_correspondence_profile(state['correspondence_type'])}\n\n"
                f"### KURALLAR:\n{rules}"
                f"{_format_style_examples(state.get('style_examples'))}"
            )
            agent = WriterAgent(client)
            temperature = 0.4

        # Streamed rather than awaited whole: the draft is the longest single
        # generation in the system, and forwarding chunks is what makes the UI
        # feel live instead of frozen behind a spinner. A revision streams
        # under the same "draft" node id, so the frontend clears any
        # in-progress streamingText on every node_start rather than only the
        # first -- otherwise the two attempts would visually concatenate.
        # The writer's budget is applied *inside* the node rather than by the
        # @node_timeout decorator. A decorator would raise past the except
        # clauses below and crash the draft graph; here a timeout becomes a
        # FAILED result carrying whatever was streamed, which is what the rest
        # of the graph already knows how to handle. This is also the first time
        # the most expensive step in the ~90s draft budget has had any node-level
        # protection at all -- resilience.py has carried a "writer" entry since
        # it was written, and nothing ever read it.
        budget = node_budget("writer", preset.level)
        chunks: list[str] = []
        try:
            async with asyncio.timeout(budget):
                async for chunk in agent.stream(
                    messages=prompt,
                    temperature=temperature,
                    max_tokens=preset.draft_max_tokens,
                    reasoning=preset.reasoning,
                ):
                    chunks.append(chunk)
                    await emit_token(config, "draft", chunk)

            draft = "".join(chunks).strip()
            if not draft:
                raise ValueError("Ajan boş taslak döndürdü.")

            # .stream() cannot run BaseAgent.validators (there is no single
            # response to check before tokens are already emitted), so the
            # same guardrail runs here instead, against the accumulated text.
            # Fails closed: an apparent injection stops the run for human
            # review rather than being fed into an automatic revision pass.
            assert_no_prompt_leak(draft)

            LLM_TOKENS.labels(agent=agent.name, kind="prompt").inc(
                client.count_tokens(prompt)
            )
            LLM_TOKENS.labels(agent=agent.name, kind="completion").inc(
                client.count_tokens(draft)
            )

            return {"draft": draft, "attempts": attempt_number, "status": "IN_PROGRESS"}
        except TimeoutError:
            # Distinguished from a generic failure because str(TimeoutError())
            # is empty -- the user would have been shown "Taslak üretilemedi: ".
            logger.warning(
                "Writer node exceeded its %.0fs budget (attempt %d, level %s).",
                budget,
                attempt_number,
                preset.level.value,
            )
            return {
                "draft": "".join(chunks).strip(),
                "attempts": attempt_number,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": (
                    f"Taslak üretimi {budget:.0f} saniyelik süre sınırını aştı; "
                    "daha düşük bir düşünme seviyesiyle yeniden deneyin."
                ),
            }
        except Exception as exc:
            logger.exception("Writer/Reviser node failed (attempt %d)", attempt_number)
            return {
                "draft": "".join(chunks).strip(),
                "attempts": attempt_number,
                "confidence_score": 0.0,
                "requires_human_approval": True,
                "status": "FAILED",
                "error": f"Taslak üretilemedi: {exc}",
            }

    def route_after_writer(state: DraftState) -> str:
        return "end" if state.get("status") == "FAILED" else "verify"

    async def verify_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        logger.info("Running Draft Verification Node...")
        await emit_node_start(
            config,
            "verify",
            "Taslak Doğrulama",
            "[Doğrulayıcı] Taslak kaynak evrak ve mevzuata karşı denetleniyor...",
        )

        draft_text = state.get("draft", "")
        classification = state.get("classification") or {}
        strict = state.get("correspondence_type") != "other_official"
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        report = verify_draft(
            draft_text,
            source_document=state.get("source_document", ""),
            context=state.get("context", ""),
            classification=classification,
            instructions=state.get("instructions", ""),
            strict=strict,
        )

        # None means the level has no opinion; defer to the global setting.
        # True/False (fast forces off, deep forces on) overrides it outright.
        judge_on = (
            settings.DRAFT_JUDGE_ENABLED
            if preset.judge_enabled is None
            else preset.judge_enabled
        )

        verdict: DraftJudgeVerdict | None = None
        if judge_on:
            # A separate node id from "verify" (even though it runs inside the
            # same LangGraph node) so the frontend can show the hybrid gate as
            # two distinct mechanisms -- deterministic groundedness vs. the
            # fast-tier judge's reasoning-based checks -- rather than one
            # opaque "doğrulama" step.
            await emit_node_start(
                config,
                "judge",
                "Kalite Yargıcı",
                "[Yargıç] Talebe uygunluk, üslup ve kapanış yönü değerlendiriliyor...",
            )
            # Scaled by the level, same as every other budget: a `deep` run
            # buys more wall clock overall and the judge is part of what it
            # buys. settings.DRAFT_JUDGE_TIMEOUT_SECONDS stays the single owner
            # of the base value -- it is a deployment knob, not a policy one.
            verdict = await judge_draft(
                judge_agent,
                draft=draft_text,
                brief=state.get("brief", ""),
                correspondence_type=state.get("correspondence_type") or "other_official",
                instructions=state.get("instructions", ""),
                timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
            )
            if verdict is None:
                await emit_node_error(
                    config,
                    "judge",
                    "Kalite Yargıcı",
                    "Kalite yargıcı kullanılamadı; deterministik doğrulama sonucuna göre devam ediliyor.",
                    fatal=False,
                )
            else:
                await emit_node_end(
                    config,
                    "judge",
                    "Kalite Yargıcı",
                    "Yargıç değerlendirmesi tamamlandı.",
                    verdict.model_dump(),
                )
        elif preset.judge_enabled is False:
            # Only announce a skip when the *level* is what turned it off --
            # the pre-existing settings.DRAFT_JUDGE_ENABLED=False case stays
            # silent, exactly as it behaved before this feature existed.
            await emit_node_skipped(
                config,
                "judge",
                "Kalite Yargıcı",
                "Hızlı modda kalite yargıcı atlandı.",
            )

        missing_information: list[InfoQuestion] = []
        if report.placeholder_count > 0:
            missing_information = build_missing_info_request(draft_text, report, classification)

        combined = merge_verdicts(report, verdict, missing_information=missing_information)

        DRAFT_SCORE.labels(source="deterministic").observe(report.confidence_score)
        if verdict is not None:
            DRAFT_SCORE.labels(source="judge").observe(verdict.score)
        DRAFT_SCORE.labels(source="combined").observe(combined.combined_score)

        # Personal data (TCKN/IBAN/phone/address) surfacing in a generated
        # draft is grounds for review the same way an unresolved
        # correspondence type is: a resmi yazışma that echoes an applicant's
        # kimlik no or address needs a human's eyes before it goes out, not a
        # second automatic revision attempt (the draft path's revision loop
        # fixes groundedness/quality defects, not confidentiality ones).
        pii_findings = [
            finding
            for finding in find_pii(draft_text)
            if finding.confidence >= get_policy().guardrail.pii_confidence_floor
        ]

        # An unresolved correspondence type or a draft with no verified
        # legislative context means the system guessed, which is itself
        # grounds for review -- and a second generation cannot fix either, so
        # this is folded into the approval decision, not into requires_revision.
        requires_approval = (
            combined.requires_human_approval
            or state.get("correspondence_type_source") == "fallback"
            or not state.get("context")
            or bool(pii_findings)
        )

        history_entry = {
            "attempt": state.get("attempts", 0),
            "deterministic_score": report.confidence_score,
            "judge_score": verdict.score if verdict is not None else None,
            "combined_score": combined.combined_score,
            "defect_count": len(combined.repair_items),
        }
        attempt_history = [*(state.get("attempt_history") or []), history_entry]

        if missing_information:
            status = "NEEDS_INPUT"
        elif requires_approval:
            status = "NEEDS_HUMAN_APPROVAL"
        else:
            status = "COMPLETED"

        evaluation_notes = combined.notes
        if pii_findings:
            kinds = ", ".join(sorted({finding.kind for finding in pii_findings}))
            evaluation_notes = (
                f"{evaluation_notes} Taslakta {len(pii_findings)} adet kişisel veri "
                f"bulgusu tespit edildi ({kinds}); insan onayı gerekiyor."
            )

        update = {
            "confidence_score": combined.combined_score,
            "combined_score": combined.combined_score,
            "requires_human_approval": requires_approval,
            "requires_revision": combined.requires_revision,
            "evaluation_notes": evaluation_notes,
            "pii_findings": [finding.model_dump() for finding in pii_findings],
            "verification": report.model_dump(),
            "judge": verdict.model_dump() if verdict is not None else {},
            "judge_available": combined.judge_available,
            "repair_items": [item.model_dump() for item in combined.repair_items],
            "missing_information": [question.model_dump() for question in missing_information],
            "attempt_history": attempt_history,
            "status": status,
            "reasoning_level": preset.level.value,
        }

        await emit_node_end(
            config,
            "verify",
            "Taslak Doğrulama",
            "Taslak doğrulaması tamamlandı.",
            {"draft": draft_text, **update},
        )
        return update

    def route_after_verify(state: DraftState) -> str:
        if state.get("status") == "FAILED":
            return "end"
        if state.get("missing_information"):
            return "needs_input"
        if not state.get("requires_revision"):
            return "end"
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        if state.get("attempts", 0) >= preset.max_draft_attempts:
            return "end"
        return "revise"

    async def revise_node(state: DraftState, config: RunnableConfig) -> dict[str, Any]:
        """Prep the next writer pass. Pure and LLM-free -- the loop's only
        generation cost is the writer/reviser call, never a second one here."""
        repair_items = state.get("repair_items") or []
        logger.info("Preparing revision (%d defect(s))...", len(repair_items))
        trigger = (
            "deterministic"
            if any(item.get("source") == "deterministic" for item in repair_items)
            else "judge"
        )
        DRAFT_REVISIONS.labels(trigger=trigger).inc()
        await emit_node_start(
            config,
            "revise",
            "Revizyon Hazırlığı",
            f"{len(repair_items)} kusur tespit edildi; hedefli düzeltme hazırlanıyor...",
        )
        update = {"previous_draft": state.get("draft", "")}
        await emit_node_end(
            config,
            "revise",
            "Revizyon Hazırlığı",
            "Düzeltme talimatları hazırlandı.",
            {"repair_items": repair_items},
        )
        return update

    builder = StateGraph(DraftState)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("retrieve_examples", retrieve_examples_node, retry_policy=IO_RETRY)
    builder.add_node("writer", writer_node)
    builder.add_node("verify", verify_node)
    builder.add_node("revise", revise_node)

    builder.add_edge(START, "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {"retrieve_examples": "retrieve_examples", "end": END},
    )
    builder.add_edge("retrieve_examples", "writer")
    builder.add_conditional_edges(
        "writer", route_after_writer, {"verify": "verify", "end": END}
    )
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {"revise": "revise", "needs_input": END, "end": END},
    )
    builder.add_edge("revise", "writer")

    return builder.compile()
