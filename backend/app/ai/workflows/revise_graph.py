"""The revision sub-graph: a real LangGraph workflow mirroring draft_graph's
own verify/repair loop and observability, instead of the single hand-rolled
function ``run_revise`` used to be.

Unlike ``draft_graph`` (classify -> write -> verify -> reflexion loop),
revise never re-classifies -- it operates directly on
``SessionFocus.active_draft``, the text the user already saw and is asking
to change. It does now conditionally re-retrieve legislation (see
``app.ai.revision.retrieval``) and now carries the same verification
guarantees ``draft_graph.verify_node`` has always had (PII gate, fallback
correspondence-type gate, few-shot leak detection, a bounded repair loop)
that the old single-call implementation did not::

    START -> parse -> retrieve_context -> rewrite -+-> verify -+-> repair -> rewrite (bounded)
                                                     \\-> end     |-> needs_input -> END
                                                                  \\-> audit -> END

Two invariants this graph never violates:

1. **User instruction supremacy.** The instruction is applied verbatim in
   ``rewrite`` before anything else runs. Nothing downstream (``verify``,
   ``repair``, ``audit``) can revert or soften it -- ``repair`` only fixes
   *deterministic/judge defects* (unsupported claims, missing structure),
   never the user's own request, and ``audit`` only attaches warnings (see
   ``app.ai.revision.conflict``'s ``applied_anyway`` invariant).
2. **Structural no-drift guarantee.** When the instruction decomposes into
   located spans, each rewrite is spliced back with ``_merge`` -- the
   untouched surrounding text is never reproduced by the model, so it
   cannot silently drift (see ``app.ai.revision.instruction`` module
   docstring). Multiple spans are applied right-to-left against the
   *original* draft so earlier (leftward) offsets are never invalidated by
   a later (rightward) splice. The two paths that regenerate the *whole*
   draft instead (no target span located; any repair-loop pass) have no
   splice to fall back on, so they get a deterministic backstop instead --
   ``verify`` runs ``app.ai.revision.elision.detect_content_loss`` against
   the turn's true starting draft on every pass, catching a model that
   elided real (already-filled-in) content with an ellipsis/shorthand
   instead of reproducing it.
"""

import asyncio
import logging
from typing import Any, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from app.ai.agents.conflict_auditor import ConflictAuditorAgent
from app.ai.agents.judge import JudgeAgent
from app.ai.agents.reviser import ReviserAgent
from app.ai.guardrails.injection import assert_no_prompt_leak, assert_no_scaffold_echo
from app.ai.guardrails.pii import find_pii
from app.ai.llms.base import BaseLLMClient
from app.ai.policy import get_policy
from app.ai.adapters.company_adapter import AdapterProvider, CompanyAdapter
from app.ai.adapters.injection import format_adapter_block
from app.ai.policy.budget import node_budget
from app.ai.reasoning_levels import ReasoningLevelPreset, get_reasoning_level_preset
from app.ai.revision.changelog import build_changelog
from app.ai.revision.conflict import (
    assess_conflicts_llm,
    detect_conflicts_deterministic,
    merge_conflicts,
)
from app.ai.revision.elision import detect_content_loss
from app.ai.revision.instruction import (
    EditDirective,
    RevisionInstruction,
    TargetSpan,
    _merge,
    locate_target,
    parse_revision_instruction,
)
from app.ai.revision.retrieval import maybe_extend_context
from app.ai.session.focus import DraftVersion
from app.ai.verification import (
    InfoQuestion,
    VerificationReport,
    build_missing_info_request,
    fill_date_placeholders,
    judge_draft,
    merge_verdicts,
    normalize_role_placeholders,
    normalize_unfilled_markers,
    verify_draft,
)
from app.ai.workflows.correspondence import format_correspondence_profile
from app.ai.workflows.events import (
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_notice,
)
from app.ai.workflows.resilience import IO_RETRY
from app.ai.workflows.writing_brief import format_writing_brief
from app.core.config import settings
from app.core.enums.step_status import StepStatus
from app.observability.ai_metrics import DRAFT_REVISIONS, DRAFT_SCORE

logger = logging.getLogger(__name__)


class ReviseState(TypedDict, total=False):
    """LangGraph state for the revision workflow."""

    #: Input, set once by the caller and never mutated by any node.
    active_draft: DraftVersion
    instructions: str
    reasoning_level: str
    #: Which tenant this revision is for -- read by `rewrite_node` to resolve
    #: this company's runtime style adapter (Faz C2, see `adapter_provider`
    #: on `create_revise_graph`). Absent/empty behaves exactly like no
    #: adapter configured, never an error.
    company_id: str
    #: Today's date (see app.ai.workflows.dates.today_tr), read by
    #: `verify_node`'s date-placeholder backstop -- a revision keeps the
    #: original draft's date unchanged by construction (see this module's
    #: own anti-date-change rule), so this only ever fires if a rewrite
    #: pass reintroduces a "Tarih:" placeholder.
    today: str

    #: Set by `parse`.
    instruction: RevisionInstruction
    directives: list[EditDirective]
    targets: list[Optional[TargetSpan]]
    #: Whether the multi-directive path is safe to use (every directive
    #: located a span) -- False falls back to a single whole/first-directive
    #: rewrite, the same safe default a single-clause instruction gets.
    multi_directive_ok: bool
    correspondence_type: str
    correspondence_type_source: str
    correspondence_sub_genre: str

    #: Set by `retrieve_context`.
    context: str
    retrieval_meta: dict[str, Any]

    #: Set by `rewrite`.
    draft: str
    previous_draft: str
    attempts: int
    error: str
    #: The resolved adapter (`CompanyAdapter.to_dict()`), carried forward so
    #: `verify` can fold `preferred_examples` into the same
    #: `ornek_sizintisi` leak check `style_examples` already goes through,
    #: without re-resolving it a second time.
    company_adapter: dict[str, Any]

    #: Set by `verify`.
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
    #: See draft_graph.DraftState's own field of the same name.
    applied_rules: list[dict[str, Any]]

    #: Set by `audit`.
    conflicts: list[dict[str, Any]]
    conflict_notes: str
    changelog: dict[str, Any]

    status: str


def _coerce_fields(classification: dict[str, Any]) -> dict[str, Any]:
    fields = (classification or {}).get("fields", {})
    if hasattr(fields, "model_dump"):
        return fields.model_dump()
    return fields if isinstance(fields, dict) else {}


def _build_brief(active_draft: DraftVersion, context: str) -> str:
    """The grounding brief handed to every reviser/judge call this run.

    Rebuilt from ``context`` (not cached) so a conditional re-retrieval
    (see ``app.ai.revision.retrieval``) is reflected in every downstream
    prompt, not just the first one.
    """
    rejection_note = ""
    if active_draft.status == "REJECTED" and active_draft.rejection_reason:
        # `active_draft` can itself be a previously rejected version (see
        # app.ai.session.focus's own docstring on _ARCHIVE_ONLY_DRAFT_STATUSES
        # -- a reject no longer clears active_draft, it stays revisable).
        # Surfacing why it was rejected keeps this revision targeted at that
        # one complaint instead of treating the whole text as suspect, which
        # is exactly what the reviser's own "yalnızca kusur listesindeki
        # maddeleri gider" contract already expects of it.
        rejection_note = (
            "5. Önceki Sürümün Reddedilme Gerekçesi (YALNIZCA bu noktaya "
            f"odaklan; metnin geri kalanındaki doğru bilgiyi koru): "
            f"{active_draft.rejection_reason}\n"
        )
    return (
        f"1. Önceki Taslak Sürümü: {active_draft.version}\n"
        f"2. Doğrulanmış Sınıflandırma: {active_draft.classification.get('summary', 'Özet yok.')}\n"
        f'3. Doğrulanmış Mevzuat Bağlamı:\n"""\n'
        f"{context or 'İlgili mevzuat bağlamı bulunamadı.'}\n\"\"\"\n"
        f"4. Yazım Briefi:\n{format_writing_brief(active_draft.writing_brief)}\n"
        f"{rejection_note}"
    )


def _format_style_examples_flat(texts: tuple[str, ...]) -> str:
    """Render the draft's own style examples as a prompt block.

    Flat text only (unlike draft_graph's richer per-example metadata
    block) -- DraftVersion carries just the texts (see
    ``app.ai.session.focus``), which is all ``verify_draft``'s leak
    detection needs and all a revision's much shorter prompts need too.
    """
    if not texts:
        return ""
    blocks = "\n\n".join(f"<ornek>\n{text}\n</ornek>" for text in texts)
    return (
        "\n\n### ÜSLUP REFERANS ÖRNEKLERİ:\n"
        "Bunlar bilgi kaynağı DEĞİLDİR, yalnızca üslup göstermek içindir. "
        "İçlerindeki hiçbir kurum, kişi, tarih veya sayıyı taslağa taşıma.\n\n"
        f"{blocks}"
    )


def _build_directive_prompt(
    *, source_draft: str, target: Optional[TargetSpan], directive: EditDirective,
    brief: str, correspondence_type: str, sub_genre: str, style_examples: tuple[str, ...],
    adapter_block: str = "",
) -> str:
    """Compose the reviser's prompt for one directive, scoped to its target
    span when one was found."""
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
            "Ne brief'te NE DE bu talimatta geçen bir yeni bilgi (kişi, kurum, tarih, "
            "sayı, mevzuat maddesi) ekleme -- ama talimatın kendisi bir isim/kurum/tarih "
            "belirtiyorsa (ör. \"muhatabı X Valiliği yap\") bunu doğrudan uygula, "
            "kullanıcının kendi belirttiği bilgi kaynak sayılır. Talimatta belirtilmeyen "
            "hiçbir alanda üslup/kapsam/uzunluk dışında bir değişiklik yapma. "
            "Talimatla ilgisi olmayan her cümleyi, önceki taslaktaki haliyle, KELİMESİ "
            "KELİMESİNE ve EKSİKSİZ olarak yeniden üret. '...', '(değişmedi)', '[aynı]' "
            "gibi kısaltma veya atlama ifadeleriyle hiçbir bölümü özetleme. Talimatla "
            "ilgisi olmayan, zaten doldurulmuş bilgileri (isim, kurum, tarih vb.) asla "
            "silme -- ANCAK talimat açıkça bir cümlenin/kısmın silinmesini, çıkarılmasını "
            "veya kaldırılmasını istiyorsa, o kısmı gerçekten sil; bu durumda '[...]' "
            "yer tutucusu bırakma, ilgili kısmı taslaktan tamamen çıkar."
        )

    return (
        "### GÖREV:\n"
        "Kullanıcı, mevcut bir resmî yazı taslağında hedefli bir değişiklik istiyor.\n\n"
        f"### BRIEF BELGESİ:\n{brief}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        f"### MEVCUT TASLAK:\n{source_draft}\n\n"
        f"{scope_rule}\n\n"
        f"### KULLANICI TALİMATI:\n{directive.raw}\n\n"
        "### ÇIKTI:\nYalnızca istenen bölümün (veya kural tüm taslağı kapsıyorsa taslağın "
        "tamamının) yeni metnini döndür. Meta yorum, markdown kod bloğu veya açıklama ekleme."
        f"{_format_style_examples_flat(style_examples)}"
        f"{adapter_block}"
    )


def _build_repair_prompt(
    *, brief: str, correspondence_type: str, sub_genre: str, previous_draft: str,
    repair_items: list[dict[str, Any]], style_examples: tuple[str, ...],
    adapter_block: str = "",
) -> str:
    """Compose the repair prompt for a second-plus attempt, after `verify`
    found deterministic/judge defects. Mirrors draft_graph._build_repair_prompt."""
    numbered = "\n".join(
        f"{index}. [{item.get('kind')}] {item.get('detail')}"
        + (f" -> Öneri: {item.get('suggested_fix')}" if item.get("suggested_fix") else "")
        for index, item in enumerate(repair_items, start=1)
    )
    return (
        "### GÖREV:\n"
        "Aşağıdaki önceki taslağı, YALNIZCA numaralı kusur listesindeki maddeleri "
        "gidererek düzelt. Listede olmayan hiçbir cümleyi değiştirme.\n\n"
        f"### BRIEF BELGESİ:\n{brief}\n\n"
        f"### YAZIŞMA TÜRÜ PROFİLİ:\n{format_correspondence_profile(correspondence_type, sub_genre)}\n\n"
        f"### ÖNCEKİ TASLAK:\n{previous_draft}\n\n"
        f"### DÜZELTİLMESİ GEREKEN KUSURLAR:\n{numbered or '(kusur listesi boş)'}\n\n"
        "### KURAL:\n"
        "Yalnızca listelenen kusurları düzelt. Başka hiçbir cümleyi değiştirme. "
        "`[...]` yer tutucularını olduğu gibi bırak. Listelenmeyen her cümleyi önceki "
        "taslaktaki haliyle, KELİMESİ KELİMESİNE ve EKSİKSİZ olarak geri döndür -- "
        "'...', '(değişmedi)', '[aynı]' gibi kısaltma veya atlama ifadeleriyle hiçbir "
        "bölümü özetleme; zaten doldurulmuş bilgileri asla silme."
        f"{_format_style_examples_flat(style_examples)}"
        f"{adapter_block}"
    )


def _resolve_free_text_client(
    preset, llm_client: BaseLLMClient, fast_llm_client: Optional[BaseLLMClient]
) -> BaseLLMClient:
    if preset.model_tier == "fast" and fast_llm_client is not None:
        return fast_llm_client
    return llm_client


def create_revise_graph(
    llm_client: BaseLLMClient,
    fast_llm_client: Optional[BaseLLMClient] = None,
    mevzuat_retriever: Optional[Any] = None,
    adapter_provider: Optional[AdapterProvider] = None,
):
    """Create and compile the revision workflow.

    Args:
        llm_client: The quality-tier LLM used by the reviser and judge.
        fast_llm_client: Optional fast-tier client for the fast reasoning
            level, the judge and the conflict auditor. Falls back to
            ``llm_client`` when omitted, same as ``draft_graph``.
        mevzuat_retriever: Optional retriever for conditional legislation
            re-retrieval (see ``app.ai.revision.retrieval``). None always
            skips re-retrieval, reproducing pre-feature behaviour exactly.
        adapter_provider: Optional async callable resolving a company's
            runtime style adapter (Faz C2, see
            ``app.domains.companies.provider.get_company_adapter``) --
            injected the same way ``draft_graph``'s own ``adapter_provider``
            is. None reproduces pre-feature behaviour exactly (no adapter
            block, ever).

    Returns:
        The compiled LangGraph workflow.
    """
    judge_agent = JudgeAgent(fast_llm_client or llm_client)
    conflict_agent = ConflictAuditorAgent(fast_llm_client or llm_client)

    async def _resolve_adapter(state: ReviseState) -> CompanyAdapter:
        """This company's runtime style adapter, or an empty one when no
        ``adapter_provider`` was configured, no ``company_id`` is on this
        turn's state, or resolution itself fails -- see
        ``draft_graph``'s identical helper for the same rationale."""
        company_id = state.get("company_id") or ""
        if not company_id or adapter_provider is None:
            return CompanyAdapter.empty(company_id)
        try:
            return await adapter_provider(company_id)
        except Exception:
            logger.warning("Company adapter resolution failed for %s", company_id, exc_info=True)
            return CompanyAdapter.empty(company_id)

    async def parse_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        instructions = state["instructions"]
        await emit_node_start(
            config, "revise_parse", "Talimat Ayrıştırma",
            "Revizyon talimatı ayrıştırılıyor...",
        )

        instruction = parse_revision_instruction(instructions)
        directives = list(instruction.directives)
        targets = [locate_target(active_draft.text, directive) for directive in directives]
        multi_directive_ok = len(directives) > 1 and all(t is not None for t in targets)

        correspondence_type = active_draft.correspondence_type
        correspondence_type_source = getattr(active_draft, "correspondence_type_source", "")
        correspondence_sub_genre = getattr(active_draft, "correspondence_sub_genre", "")

        await emit_node_end(
            config, "revise_parse", "Talimat Ayrıştırma",
            f"{len(directives)} direktif tespit edildi." if multi_directive_ok
            else "Talimat tek parça olarak işlenecek.",
            {"directive_count": len(directives), "multi_directive": multi_directive_ok},
        )

        return {
            "instruction": instruction,
            "directives": directives,
            "targets": targets,
            "multi_directive_ok": multi_directive_ok,
            "correspondence_type": correspondence_type,
            "correspondence_type_source": correspondence_type_source,
            "correspondence_sub_genre": correspondence_sub_genre,
            "context": active_draft.context,
            "draft": active_draft.text,
            "attempts": 0,
            "status": "IN_PROGRESS",
        }

    async def retrieve_context_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        instruction = state["instruction"]
        await emit_node_start(
            config, "revise_retrieve", "Mevzuat Kontrolü",
            "Talimatın mevzuat bağlamı yeniden getirim gerektirip gerektirmediği kontrol ediliyor...",
        )

        context, meta = await maybe_extend_context(
            instruction=instruction, active_draft=active_draft, retriever=mevzuat_retriever,
        )

        if meta["decision"] == "extended":
            await emit_node_end(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                f"{meta['added']} yeni mevzuat alıntısı eklendi.", meta,
            )
        elif meta["decision"] == "failed":
            await emit_node_error(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                "Mevzuat yeniden getirimi başarısız; mevcut bağlamla devam ediliyor.",
                fatal=False,
            )
        else:
            await emit_node_skipped(
                config, "revise_retrieve", "Mevzuat Kontrolü",
                "Bu talimat için yeniden getirim gerekmedi.",
            )

        return {"context": context, "retrieval_meta": meta}

    async def _generate_validated(
        agent: ReviserAgent, prompt: str, preset: ReasoningLevelPreset
    ) -> str:
        """Run one reviser call, fully buffered, validated before anything
        reaches the client.

        Nothing is emitted to the "revise" SSE node here -- see
        ``rewrite_node``'s own docstring for why. A single reviser call can
        run several times per turn (once per directive in the
        multi-directive path, again on every repair round), and the old
        per-chunk ``emit_token`` streamed each of those raw completions
        live, unvalidated, straight into the chat: a completion that echoed
        its own numbered brief scaffold (a known failure mode of smaller
        local models given a heavily-structured prompt like this one) or
        that simply ran twice in the same turn showed up in the chat as
        literal "1. ... 2. ..." garbage concatenated across rounds with no
        boundary between them. Buffering here and validating before
        ``rewrite_node`` emits anything makes both impossible structurally,
        not just less likely.

        Raises:
            ValueError: Empty completion.
            GuardrailViolation: A prompt-injection or scaffold-echo pattern
                was detected (see ``app.ai.guardrails.injection``).
        """
        chunks: list[str] = []
        async for chunk in agent.stream(
            messages=prompt, temperature=0.2, max_tokens=preset.draft_max_tokens,
            reasoning=preset.reasoning,
        ):
            chunks.append(chunk)
        rewritten = "".join(chunks).strip()
        if not rewritten:
            raise ValueError("Ajan boş bir revizyon döndürdü.")
        assert_no_prompt_leak(rewritten)
        assert_no_scaffold_echo(rewritten)
        return rewritten

    async def rewrite_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Rewrite (or repair) the draft, buffering the model's output until
        it has passed validation before anything is shown to the user.

        The reviser's own prompts (``_build_brief``, ``_build_directive_
        prompt``, ``_build_repair_prompt``) are dense, numbered scaffolding
        by necessity -- a smaller local model asked to continue that shape
        sometimes imitates it in its completion instead of producing plain
        draft prose. Streaming that live, chunk by chunk, as the old
        implementation did, put the leak on screen before any check could
        run. Buffering through ``_generate_validated`` and only then
        emitting the *validated* text (once, as a single token event just
        before ``emit_node_end``) closes that gap without touching what the
        user ultimately sees on a clean run -- the final draft text is
        identical either way.
        """
        active_draft = state["active_draft"]
        attempt_number = state.get("attempts", 0) + 1
        is_repair = bool(state.get("previous_draft"))
        preset = get_reasoning_level_preset(state.get("reasoning_level"))
        client = _resolve_free_text_client(preset, llm_client, fast_llm_client)
        brief = _build_brief(active_draft, state.get("context", ""))
        correspondence_type = state.get("correspondence_type") or active_draft.correspondence_type
        sub_genre = state.get("correspondence_sub_genre") or getattr(
            active_draft, "correspondence_sub_genre", ""
        )
        style_examples = active_draft.style_examples
        # Resolved once per attempt (Redis-cached in the real provider, see
        # app.domains.companies.provider.get_company_adapter), same as
        # draft_graph.writer_node's identical call.
        adapter = await _resolve_adapter(state)
        adapter_block = format_adapter_block(adapter)

        await emit_node_start(
            config, "revise", "Taslak Revizyonu",
            f"[Revizyon Ajanı] Taslak {attempt_number}. denemede "
            + ("düzeltiliyor..." if is_repair else "yeniden yazılıyor..."),
        )

        budget = node_budget("revise", preset.level)
        try:
            async with asyncio.timeout(budget):
                if is_repair:
                    prompt = _build_repair_prompt(
                        brief=brief, correspondence_type=correspondence_type,
                        sub_genre=sub_genre,
                        previous_draft=state.get("previous_draft", ""),
                        repair_items=state.get("repair_items") or [],
                        style_examples=style_examples,
                        adapter_block=adapter_block,
                    )
                    agent = ReviserAgent(client)
                    merged_draft = await _generate_validated(agent, prompt, preset)
                else:
                    directives = state["directives"]
                    targets = state["targets"]
                    multi_directive_ok = state.get("multi_directive_ok", False)
                    agent = ReviserAgent(client)

                    if multi_directive_ok:
                        # Right-to-left: spans were computed against the
                        # original draft, so processing the rightmost span
                        # first means every not-yet-processed (leftward)
                        # span's offsets stay valid against the
                        # progressively-spliced working draft (see module
                        # docstring).
                        order = sorted(
                            range(len(directives)), key=lambda i: targets[i].start, reverse=True
                        )
                        working_draft = active_draft.text
                        for i in order:
                            prompt = _build_directive_prompt(
                                source_draft=active_draft.text, target=targets[i],
                                directive=directives[i], brief=brief,
                                correspondence_type=correspondence_type,
                                sub_genre=sub_genre,
                                style_examples=style_examples,
                                adapter_block=adapter_block,
                            )
                            rewritten = await _generate_validated(agent, prompt, preset)
                            working_draft = _merge(working_draft, targets[i], rewritten)
                        merged_draft = working_draft
                    else:
                        # Single clause (the common case) or a multi-clause
                        # instruction that could not locate every span --
                        # falls back to the same safe whole/first-directive
                        # rewrite a single-clause instruction always got.
                        directive = directives[0]
                        target = targets[0]
                        prompt = _build_directive_prompt(
                            source_draft=active_draft.text, target=target, directive=directive,
                            brief=brief, correspondence_type=correspondence_type,
                            sub_genre=sub_genre,
                            style_examples=style_examples,
                            adapter_block=adapter_block,
                        )
                        rewritten = await _generate_validated(agent, prompt, preset)
                        merged_draft = _merge(active_draft.text, target, rewritten)
        except TimeoutError:
            logger.warning(
                "Revise rewrite node exceeded its %.0fs budget (attempt %d).", budget, attempt_number
            )
            await emit_node_error(
                config, "revise", "Taslak Revizyonu",
                f"Revizyon {budget:.0f} saniyelik süre sınırını aştı.", fatal=True,
            )
            return {
                "draft": active_draft.text, "attempts": attempt_number,
                "confidence_score": 0.0, "combined_score": 0.0,
                "requires_human_approval": True, "status": StepStatus.FAILED,
                "error": f"Revizyon {budget:.0f} saniyelik süre sınırını aştı.",
            }
        except Exception as exc:
            logger.exception("Revise rewrite node failed (attempt %d)", attempt_number)
            await emit_node_error(
                config, "revise", "Taslak Revizyonu", "Revizyon üretilemedi.", detail=str(exc),
            )
            return {
                "draft": active_draft.text, "attempts": attempt_number,
                "confidence_score": 0.0, "combined_score": 0.0,
                "requires_human_approval": True, "status": StepStatus.FAILED,
                "error": f"Revizyon üretilemedi: {exc}",
            }

        # No token is emitted here -- see _generate_validated's docstring.
        # The validated text is only ever streamed to the client once, from
        # chat_service._enqueue_terminal_event, after the whole turn (verify,
        # any repair pass, guardrails) has settled on its final reply.
        await emit_node_end(
            config, "revise", "Taslak Revizyonu", "Revizyon tamamlandı.", {"draft": merged_draft},
        )
        return {
            "draft": merged_draft,
            "attempts": attempt_number,
            "status": "IN_PROGRESS",
            "company_adapter": adapter.to_dict(),
        }

    def route_after_rewrite(state: ReviseState) -> str:
        return "end" if state.get("status") == StepStatus.FAILED else "verify"

    async def verify_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        active_draft = state["active_draft"]
        # Same backstop as draft_graph.verify_node -- a repair/rewrite pass
        # can leave the same literal "bulunamadı"/"yok" marker the original
        # writer could, and revise never re-runs the original writer's
        # prompt to begin with.
        draft_text, _ = normalize_unfilled_markers(state.get("draft", ""))
        draft_text, _ = fill_date_placeholders(draft_text, state.get("today", ""))
        correspondence_type = state.get("correspondence_type") or active_draft.correspondence_type
        sub_genre = state.get("correspondence_sub_genre") or getattr(
            active_draft, "correspondence_sub_genre", ""
        )
        # Same backstop as draft_graph.verify_node -- see its own note.
        draft_text, _ = normalize_role_placeholders(
            draft_text, is_individual_petition="dilekçe" in sub_genre.lower()
        )
        strict = correspondence_type != "other_official"
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        await emit_node_start(
            config, "verify", "Taslak Doğrulama",
            "[Doğrulayıcı] Revize taslak kaynak evrak ve mevzuata karşı denetleniyor...",
        )

        # Same fold-in as draft_graph.verify_node -- the adapter's own
        # preferred_examples get the exact same ornek_sizintisi leak check
        # as every other style example (see CompanyAdapter's docstring).
        adapter = CompanyAdapter.from_dict(
            state.get("company_id") or "", state.get("company_adapter")
        )
        report = verify_draft(
            draft_text,
            source_document=active_draft.source_document,
            context=state.get("context", ""),
            classification=active_draft.classification,
            instructions=state.get("instructions", ""),
            strict=strict,
            style_examples=list(active_draft.style_examples) + list(adapter.preferred_examples),
            is_individual_petition="dilekçe" in sub_genre.lower(),
            today=state.get("today", ""),
        )

        judge_on = (
            settings.DRAFT_JUDGE_ENABLED if preset.judge_enabled is None else preset.judge_enabled
        )
        verdict = None
        if judge_on:
            await emit_node_start(
                config, "judge", "Kalite Yargıcı",
                "[Yargıç] Revizyonun talebe uygunluğu değerlendiriliyor...",
            )
            verdict = await judge_draft(
                judge_agent,
                draft=draft_text,
                brief=_build_brief(active_draft, state.get("context", "")),
                correspondence_type=correspondence_type,
                instructions=state.get("instructions", ""),
                timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
                sub_genre=sub_genre,
            )
            if verdict is None:
                await emit_node_error(
                    config, "judge", "Kalite Yargıcı",
                    "Kalite yargıcı kullanılamadı; deterministik doğrulama sonucuna göre devam ediliyor.",
                    fatal=False,
                )
            else:
                await emit_node_end(
                    config, "judge", "Kalite Yargıcı", "Yargıç değerlendirmesi tamamlandı.",
                    verdict.model_dump(),
                )
        elif preset.judge_enabled is False:
            await emit_node_skipped(
                config, "judge", "Kalite Yargıcı", "Hızlı modda kalite yargıcı atlandı.",
            )

        missing_information: list[InfoQuestion] = []
        if report.placeholder_count > 0:
            missing_information = build_missing_info_request(
                draft_text, report, active_draft.classification
            )

        # Neither of the two paths that can produce `draft_text` without
        # splicing through `_merge` (a whole-draft rewrite with no located
        # target, or any repair-loop pass -- see rewrite_node) had anything
        # checking that the model actually reproduced what it wasn't asked
        # to change. Compared against `active_draft.text` specifically (the
        # turn's true starting point, not a possibly-already-elided repair
        # attempt) so a loss introduced on attempt 1 is still caught on
        # attempt 2's check, not laundered away as "no further loss".
        content_loss = detect_content_loss(
            active_draft.text, draft_text, state.get("instructions", "")
        )
        if content_loss is not None:
            logger.warning("Revise rewrite dropped content: %s", content_loss.detail)

        # Parity with draft_graph.verify_node: a revision that introduces
        # PII, or that inherited a guessed (fallback) correspondence type,
        # or that has no legislation grounding at all, needs a human's
        # eyes -- the old single-call run_revise checked none of these.
        pii_findings = [
            finding
            for finding in find_pii(draft_text)
            if finding.confidence >= get_policy().guardrail.pii_confidence_floor
        ]

        combined = merge_verdicts(
            report,
            verdict,
            missing_information=missing_information,
            pii_findings=pii_findings,
            correspondence_type_fallback=state.get("correspondence_type_source") == "fallback",
            has_context=bool(state.get("context")),
            content_loss=content_loss,
        )

        DRAFT_SCORE.labels(source="deterministic").observe(report.confidence_score)
        if verdict is not None:
            DRAFT_SCORE.labels(source="judge").observe(verdict.score)
        DRAFT_SCORE.labels(source="combined").observe(combined.combined_score)

        history_entry = {
            "attempt": state.get("attempts", 0),
            "deterministic_score": report.confidence_score,
            "judge_score": verdict.score if verdict is not None else None,
            "combined_score": combined.combined_score,
            "defect_count": len(combined.repair_items),
        }
        attempt_history = [*(state.get("attempt_history") or []), history_entry]

        if missing_information:
            status = StepStatus.NEEDS_INPUT
        elif combined.requires_human_approval:
            status = StepStatus.NEEDS_HUMAN_APPROVAL
        else:
            status = StepStatus.COMPLETED

        evaluation_notes = combined.notes
        if pii_findings:
            kinds = ", ".join(sorted({finding.kind for finding in pii_findings}))
            evaluation_notes = (
                f"{evaluation_notes} Taslakta {len(pii_findings)} adet kişisel veri "
                f"bulgusu tespit edildi ({kinds}); insan onayı gerekiyor."
            )
        if content_loss is not None:
            evaluation_notes = f"{evaluation_notes} {content_loss.detail}"

        update = {
            "draft": draft_text,
            "confidence_score": combined.combined_score,
            "combined_score": combined.combined_score,
            "requires_human_approval": combined.requires_human_approval,
            "requires_revision": combined.requires_revision,
            "evaluation_notes": evaluation_notes,
            "pii_findings": [finding.model_dump() for finding in pii_findings],
            "verification": report.model_dump(),
            "judge": verdict.model_dump() if verdict is not None else {},
            "judge_available": combined.judge_available,
            "repair_items": [item.model_dump() for item in combined.repair_items],
            "missing_information": [q.model_dump() for q in missing_information],
            "attempt_history": attempt_history,
            "status": status,
            "applied_rules": [rule.model_dump() for rule in combined.applied_rules],
        }
        await emit_node_end(
            config, "verify", "Taslak Doğrulama", "Taslak doğrulaması tamamlandı.",
            {"draft": draft_text, **update},
        )
        return update

    def route_after_verify(state: ReviseState) -> str:
        if state.get("status") == StepStatus.FAILED:
            return "end"
        if state.get("missing_information"):
            return "needs_input"
        if state.get("requires_revision"):
            preset = get_reasoning_level_preset(state.get("reasoning_level"))
            if state.get("attempts", 0) < preset.max_draft_attempts:
                return "repair"
        return "audit"

    async def repair_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Prep the next rewrite pass. Pure and LLM-free, same role as
        draft_graph.revise_node -- the loop's only generation cost is the
        rewrite call, never a second one here."""
        repair_items = state.get("repair_items") or []
        trigger = (
            "deterministic"
            if any(item.get("source") == "deterministic" for item in repair_items)
            else "judge"
        )
        DRAFT_REVISIONS.labels(trigger=trigger).inc()
        await emit_node_start(
            config, "revise_repair", "Revizyon Onarımı",
            f"{len(repair_items)} kusur tespit edildi; hedefli düzeltme hazırlanıyor...",
        )
        update = {"previous_draft": state.get("draft", "")}
        await emit_node_end(
            config, "revise_repair", "Revizyon Onarımı", "Düzeltme talimatları hazırlandı.",
            {"repair_items": repair_items},
        )
        return update

    async def audit_node(state: ReviseState, config: RunnableConfig) -> dict[str, Any]:
        """Instruction-vs-mevzuat/source conflict audit and change log.

        Runs only on a settled, non-missing-information outcome -- there is
        no point auditing a draft the user is about to be asked more
        questions about (see route_after_verify's `needs_input` shortcut,
        which skips this node entirely).

        A conflict finding here is advisory, never a gate: ``ConflictReport.
        applied_anyway`` (see ``app.ai.revision.conflict``'s module
        docstring) is a hard invariant, so this node must not turn a finding
        into a reason the turn pauses for a human. It used to -- escalating
        ``status`` to ``NEEDS_HUMAN_APPROVAL`` whenever
        ``conflict_report.requires_human_approval`` was set -- which is what
        put "Talimatınız uygulandı, ancak..." behind the same blocking
        approval popup a genuine low-quality draft gets, indistinguishable
        from an actual decision the run needed from the user. A conflict
        now only ever produces a non-blocking ``notice`` event (see
        ``emit_notice``) rendered as its own chat message; ``status`` here
        reflects only what ``verify_node`` already decided.
        """
        active_draft = state["active_draft"]
        instruction = state["instruction"]
        draft_text = state.get("draft", "")
        preset = get_reasoning_level_preset(state.get("reasoning_level"))

        await emit_node_start(
            config, "revise_audit", "Çelişki Denetimi",
            "Talimat mevzuat ve kaynak evrakla karşılaştırılıyor...",
        )

        report = VerificationReport(**state.get("verification", {}))
        deterministic = detect_conflicts_deterministic(
            instruction=instruction, context=state.get("context", ""),
            source_document=active_draft.source_document, report=report,
        )

        judge_on = (
            settings.DRAFT_JUDGE_ENABLED if preset.judge_enabled is None else preset.judge_enabled
        )
        llm_findings = []
        if settings.REVISION_CONFLICT_AUDIT_ENABLED and judge_on:
            llm_findings = await assess_conflicts_llm(
                conflict_agent, instruction=instruction.raw, revised_draft=draft_text,
                context=state.get("context", ""), source_document=active_draft.source_document,
                timeout_s=settings.DRAFT_JUDGE_TIMEOUT_SECONDS * preset.timeout_multiplier,
            )

        conflict_report = merge_conflicts(deterministic, llm_findings)
        changelog = build_changelog(active_draft.text, draft_text, state.get("directives") or [])

        # Advisory only -- see this node's own docstring. Whether the turn
        # pauses for a human is entirely verify_node's call; a conflict
        # finding never adds to it.
        requires_approval = bool(state.get("requires_human_approval"))
        status = state.get("status")

        if conflict_report.conflicts:
            severity_label = {"critical": "Kritik", "major": "Önemli", "minor": "Küçük"}
            lines = "\n".join(
                f"- [{severity_label.get(f.severity, f.severity)}] {f.detail}"
                for f in conflict_report.conflicts
            )
            await emit_notice(
                config,
                node="revise_audit",
                title="Talimat uygulandı, ancak bir çelişki tespit edildi",
                message=(
                    "Talimatınız taslağa uygulandı; ancak mevzuat veya kaynak "
                    f"evrakla şu noktalarda çelişiyor:\n{lines}"
                ),
            )

        await emit_node_end(
            config, "revise_audit", "Çelişki Denetimi", conflict_report.notes,
            {"conflicts": [f.model_dump() for f in conflict_report.conflicts]},
        )
        return {
            "conflicts": [f.model_dump() for f in conflict_report.conflicts],
            "conflict_notes": conflict_report.notes,
            "changelog": changelog.model_dump(),
            "requires_human_approval": requires_approval,
            "status": status,
        }

    builder = StateGraph(ReviseState)
    builder.add_node("parse", parse_node)
    builder.add_node("retrieve_context", retrieve_context_node, retry_policy=IO_RETRY)
    builder.add_node("rewrite", rewrite_node)
    builder.add_node("verify", verify_node)
    builder.add_node("repair", repair_node)
    builder.add_node("audit", audit_node)

    builder.add_edge(START, "parse")
    builder.add_edge("parse", "retrieve_context")
    builder.add_edge("retrieve_context", "rewrite")
    builder.add_conditional_edges(
        "rewrite", route_after_rewrite, {"verify": "verify", "end": END}
    )
    builder.add_conditional_edges(
        "verify", route_after_verify,
        {"repair": "repair", "needs_input": END, "audit": "audit", "end": END},
    )
    builder.add_edge("repair", "rewrite")
    builder.add_edge("audit", END)

    return builder.compile()
