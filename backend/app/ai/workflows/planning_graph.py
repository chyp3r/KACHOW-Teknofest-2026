import asyncio
import hashlib
import json
import logging
import os
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.ai.agents.chat import ChatAgent
from app.ai.agents.document_qa import DocumentQAAgent
from app.ai.embeddings.models import BaseEmbeddingsClient
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.ai.verification import apply_answers, verify_draft
from app.ai.workflows.events import (
    child_config,
    emit,
    emit_interrupt,
    emit_node_end,
    emit_node_error,
    emit_node_skipped,
    emit_node_start,
    emit_partial,
    emit_token,
)
from app.ai.workflows.planner import resolve_plan
from app.core.config import settings
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.observability.ai_metrics import HITL_INTERRUPTS

logger = logging.getLogger(__name__)

QA_COLLECTION_NAME = "document_qa"
QA_RESULT_LIMIT = 4

STEP_LABELS = {
    "classification": "Evrak Analizi",
    "rag": "Mevzuat Tarama",
    "draft": "Taslak Oluşturma",
    "routing": "Birim Yönlendirme",
    "chat": "Sohbet",
    "document_qa": "Belge Soru-Cevap",
}

STEP_MESSAGES = {
    "classification": "Belge sınıflandırılıyor ve üst veriler çıkarılıyor...",
    "rag": "Mevzuat veri tabanında ilgili maddeler taranıyor...",
    "draft": "Resmî cevap taslağı hazırlanıyor...",
    "routing": "Cevap taslağının iletileceği birim analiz ediliyor...",
    "chat": "Sohbet yanıtı hazırlanıyor...",
    "document_qa": "Belge içeriği doğrultusunda cevap aranıyor...",
}

#: A step whose dependency's own result carries status FAILED must not run on
#: empty/garbage input. Without this a failed draft still let routing run on
#: draft="" and route to human approval -- an outcome visually identical to a
#: real routing decision (see planning_graph D6 in the implementation notes).
_STEP_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "draft": ("classification",),
    "routing": ("draft",),
}


def _dependency_failed(
    step: str, state: "PlanningState", updates: dict[str, Any]
) -> Optional[str]:
    """Return the name of a failed dependency for ``step``, if any.

    Args:
        step: The plan step about to run.
        state: The graph state as of the start of this superstep.
        updates: Updates already computed earlier in this same superstep
            (a dependency that just ran this turn is not yet in ``state``).

    Returns:
        The failed dependency's step name, or None when every dependency (if
        any) succeeded or has not run yet.
    """
    for dependency in _STEP_DEPENDENCIES.get(step, ()):
        result = updates.get(f"{dependency}_result") or state.get(f"{dependency}_result") or {}
        if result.get("status") == "FAILED":
            return dependency
    return None


#: Turns kept across messages on the same thread. ~6 exchanges is enough for
#: pronoun/ellipsis resolution ("evet, hazırla" after "taslak ister misiniz?")
#: without growing the prompt sent to chat/document_qa without bound.
HISTORY_WINDOW = 12


def _append_history(
    left: list[dict[str, str]] | None, right: list[dict[str, str]] | None
) -> list[dict[str, str]]:
    """LangGraph reducer: concatenate turns and keep only the trailing window.

    Args:
        left: The channel's existing value.
        right: The update returned by a node this superstep.

    Returns:
        The combined, trimmed history.
    """
    combined = [*(left or []), *(right or [])]
    return combined[-HISTORY_WINDOW:]


class PlanningState(TypedDict, total=False):
    """LangGraph state for the master orchestration workflow."""

    input_text: str
    document_id: str | None
    plan_steps: list[str]
    plan_intent: str
    current_step_idx: int
    cached_document: dict[str, Any]
    classification_result: dict[str, Any]
    rag_result: dict[str, Any]
    draft_result: dict[str, Any]
    routing_result: dict[str, Any]
    chat_result: dict[str, Any]
    document_qa_result: dict[str, Any]
    final_output: dict[str, Any]
    #: Persists across separate ainvoke() calls on the same checkpointer
    #: thread_id (see ChatService._thread_id) -- this is the whole memory
    #: story; there is no separate store to keep consistent with it.
    history: Annotated[list[dict[str, str]], _append_history]


def _requested_correspondence_type(classification: dict[str, Any]) -> str | None:
    """Read an explicitly classified output correspondence type.

    Args:
        classification: Combined analysis result.

    Returns:
        The requested correspondence type, when the metadata carries one.
    """
    metadata = classification.get("metadata", {}) or {}
    return classification.get("correspondence_type") or metadata.get(
        "correspondence_type"
    )


def _load_cached_document(document_id: str | None) -> dict[str, Any]:
    """Read the cached analysis and extracted text for an uploaded document.

    Args:
        document_id: The document's storage path, or None.

    Returns:
        The cache payload, or an empty dict when there is nothing to load.
    """
    if not document_id:
        return {}

    cache_file = os.path.join(
        settings.LOCAL_STORAGE_DIR, f"{document_id}_analysis.json"
    )
    if not os.path.exists(cache_file):
        return {}

    try:
        with open(cache_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        logger.exception("Failed to read cached analysis for %s", document_id)
        return {}


def _mevzuat_context(classification: dict[str, Any]) -> str:
    """Render the legislation the analysis step already retrieved.

    The draft flow no longer runs a separate RAG step. The analysis sub-graph
    retrieves legislation for the document as part of its own work, so a second
    retrieval pass repeated the same query behind an extra LLM call and
    discarded the first result.

    Args:
        classification: The analysis result.

    Returns:
        The excerpts as prompt context, or an empty string.
    """
    parts: list[str] = []

    for index, document in enumerate(classification.get("mevzuat_documents") or [], 1):
        content = getattr(document, "page_content", None)
        if content:
            source = getattr(document, "metadata", {}).get("mevzuat", "bilinmiyor")
            parts.append(f"[DOKÜMAN {index}] (Kaynak: {source})\n{content}")

    for item in classification.get("mevzuat_suggestions") or []:
        if isinstance(item, dict) and item.get("mevzuat"):
            parts.append(f"[MEVZUAT] {item['mevzuat']}: {item.get('aciklama', '')}")

    return "\n\n".join(parts)


def _prior_turns(state: PlanningState, limit: int) -> list[dict[str, str]]:
    """History entries from before the current turn, most-recent last.

    ``planning_node`` always appends the current user turn to ``history``
    before ``chat``/``document_qa`` run, so the last entry is always the
    message being answered right now -- excluded here, or it would appear
    twice once the agent appends it again as the live query turn.

    Args:
        state: Current graph state.
        limit: Maximum number of prior turns to return.

    Returns:
        Up to ``limit`` prior turns, oldest first.
    """
    history = state.get("history") or []
    prior = history[:-1] if history else []
    return prior[-limit:] if limit > 0 else []


def create_planning_graph(
    llm_client: BaseLLMClient,
    document_analysis_graph: Any,
    rag_graph: Any,
    draft_graph: Any,
    routing_graph: Any,
    vector_store: BaseVectorStore | None = None,
    embeddings_client: BaseEmbeddingsClient | None = None,
    fast_llm_client: Optional[BaseLLMClient] = None,
    checkpointer: Any = None,
):
    """Create and compile the master orchestration workflow.

    Planning is deterministic (see :mod:`app.ai.workflows.planner`). The previous
    implementation asked a model to choose from a fixed four-way decision table,
    which cost a structured generation plus a retry loop on every single request
    and needed sixty lines of output-shape repair to be usable at all.

    Args:
        llm_client: Quality-tier model, used for chat and document Q&A.
        document_analysis_graph: Compiled analysis sub-graph.
        rag_graph: Compiled retrieval sub-graph.
        draft_graph: Compiled drafting sub-graph.
        routing_graph: Compiled routing sub-graph.
        vector_store: Vector store backing document Q&A.
        embeddings_client: Embeddings client backing document Q&A.
        fast_llm_client: Small model for intent classification on ambiguous
            messages. Falls back to ``llm_client``.
        checkpointer: Optional LangGraph checkpointer (see
            ``app.infrastructure.checkpointing``). Required for the
            ``human_gate`` node's ``interrupt()`` calls to actually pause and
            resume the run; without one, HITL steps are skipped and the graph
            falls through as if they never triggered -- degraded, not broken.
            Only this graph gets a checkpointer: the four sub-graphs are
            invoked via ``.ainvoke()`` from inside ``execute_step_node``
            rather than registered as nodes, so they are independent Pregel
            instances that would each need their own unrelated checkpoint
            lineage.

    Returns:
        The compiled LangGraph workflow.
    """
    has_checkpointer = checkpointer is not None
    chat_agent = ChatAgent(llm_client)
    document_qa_agent = DocumentQAAgent(llm_client)
    intent_client = fast_llm_client or llm_client
    # Unfit on purpose, same as the indexing side (documents/service.py):
    # its sparse indices are corpus-independent CRC32 hashes, and query-side
    # IDF weights default to a uniform 1.0 without a fitted vocabulary, which
    # is still a meaningful lexical signal for RRF fusion against the dense
    # vector.
    qa_sparse_encoder = SparseBM25Encoder()

    async def planning_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Resolve the execution plan. Sub-millisecond in the common case."""
        await emit_node_start(
            config, "planning", "Planlama", "İş planı hazırlanıyor..."
        )

        decision = await resolve_plan(
            state["input_text"],
            state.get("document_id"),
            intent_client,
            previous_intent=state.get("plan_intent"),
        )
        logger.info(
            "Plan: %s (intent=%s, source=%s)",
            decision.steps,
            decision.intent,
            decision.source,
        )

        await emit(
            config,
            {
                "event": "planning_completed",
                "plan_steps": decision.steps,
                "intent": decision.intent,
                "reasoning": decision.reasoning,
            },
        )

        return {
            "plan_steps": decision.steps,
            "plan_intent": decision.intent,
            "current_step_idx": 0,
            "cached_document": _load_cached_document(state.get("document_id")),
            "classification_result": {},
            "rag_result": {},
            "draft_result": {},
            "routing_result": {},
            "chat_result": {},
            "document_qa_result": {},
            "final_output": {},
            "history": [{"role": "user", "content": state["input_text"]}],
        }

    async def _run_classification(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        cached = state.get("cached_document") or {}
        if cached.get("analysis"):
            logger.info("Using cached analysis for document %s", state.get("document_id"))
            analysis = cached["analysis"]
            await emit_partial(config, "classification", analysis)
            # The live path's compliance node only ever turns 'running'
            # (derived from classification's own node_start) to 'completed'
            # via this partial_result. The cached path never invokes the
            # analysis sub-graph at all, so without replaying it here, a
            # document analyzed earlier and then drafted from cache left the
            # frontend's 'Uygunluk' node stuck amber forever.
            await emit_partial(
                config,
                "compliance",
                {
                    "compliance_status": analysis.get("compliance_status"),
                    "missing_fields": analysis.get("missing_fields") or [],
                },
            )

            # Likewise replay the "rag" node's own start/end (D1): the live
            # path's retrieve_mevzuat_node now emits these for itself, and the
            # cached path must mirror that so 'Mevzuat' doesn't sit at 'todo'
            # forever -- there is no sub-graph invocation here to emit them.
            mevzuat_references = analysis.get("mevzuat_references") or []
            await emit_node_start(
                config, "rag", "Mevzuat Tarama", "Önbellekteki mevzuat sonuçları yükleniyor..."
            )
            await emit_node_end(
                config,
                "rag",
                "Mevzuat Tarama",
                f"{len(mevzuat_references)} mevzuat alıntısı yüklendi (önbellek).",
                {
                    "search_query": "",
                    "documents": [],
                    "context": "\n\n".join(
                        f"[MEVZUAT] {item.get('mevzuat', '')}: {item.get('aciklama', '')}"
                        for item in mevzuat_references
                        if isinstance(item, dict) and item.get("mevzuat")
                    ),
                },
            )

            await emit_node_end(
                config,
                "classification",
                "Evrak Analizi",
                "Evrak analizi tamamlandı (önbellek).",
                {"mevzuat_suggestions": mevzuat_references},
            )
            return analysis

        return await document_analysis_graph.ainvoke(
            {"input_text": state["input_text"], "is_ocr_text": False},
            config=child_config(config),
        )

    async def _run_draft(
        state: PlanningState, classification: dict[str, Any], config: RunnableConfig
    ) -> dict[str, Any]:
        cached = state.get("cached_document") or {}
        source_document = cached.get("extracted_text") or state["input_text"]

        context = state.get("rag_result", {}).get("context") or _mevzuat_context(
            classification
        )

        return await draft_graph.ainvoke(
            {
                "source_document": source_document,
                "classification": classification,
                "correspondence_type": _requested_correspondence_type(classification),
                "context": context,
                "instructions": (
                    f"Kullanıcı İsteği: {state['input_text']}\n\n"
                    "Gelen evraka, evrakın amacı ve doğrulanmış bağlam doğrultusunda "
                    "resmî ve kurumsal bir Türkçe yanıt taslağı oluştur."
                ),
                "attempts": 0,
            },
            config=child_config(config),
        )

    async def _run_document_qa(
        state: PlanningState, classification: dict[str, Any], config: RunnableConfig
    ) -> dict[str, Any]:
        document_id = state.get("document_id")
        if not document_id:
            return {
                "reply": "Soru sorulacak bir belge belirtilmedi.",
                "status": "FAILED",
            }

        cached = state.get("cached_document") or {}
        analysis = classification or cached.get("analysis") or {}

        summary = analysis.get("summary") or "Özet verisi mevcut değil."
        raw_metadata = analysis.get("fields") or analysis.get("metadata") or {}
        metadata = (
            json.dumps(raw_metadata, ensure_ascii=False, indent=2, default=str)
            if isinstance(raw_metadata, dict)
            else str(raw_metadata)
        )

        passages: list[str] = []
        if vector_store and embeddings_client:
            try:
                query_vector = await embeddings_client.embed_query(state["input_text"])
                sparse_indices, sparse_values = qa_sparse_encoder.encode_query(
                    state["input_text"]
                )
                # filter_dict scopes both the dense and sparse prefetch branches
                # to this document's chunks before Qdrant fuses them (RRF), so
                # the vector similarity ranking only ever runs over this
                # document rather than the whole document_qa collection.
                hits = await vector_store.hybrid_search(
                    collection_name=QA_COLLECTION_NAME,
                    query_vector=query_vector,
                    sparse_indices=sparse_indices,
                    sparse_values=sparse_values,
                    limit=QA_RESULT_LIMIT,
                    filter_dict={"storage_path": document_id},
                )
                passages = [hit["text"] for hit in hits if hit.get("text")]
            except Exception:
                logger.exception("Document Q&A vector search failed")

        # The extracted text is the reliable fallback. Vector search can miss
        # when the document was indexed under different settings, and answering
        # from the cached text beats refusing to answer at all.
        if not passages and cached.get("extracted_text"):
            passages = [cached["extracted_text"][:8000]]

        context = (
            f"--- BELGE ÖZETİ ---\n{summary}\n\n"
            f"--- BELGE ÜSTVERİSİ ---\n{metadata}\n\n"
            f"--- BELGE İÇERİĞİ ---\n"
            + ("\n\n---\n\n".join(passages) if passages else "İçerik bulunamadı.")
        )

        chunks: list[str] = []
        try:
            async for chunk in document_qa_agent.answer_stream(
                context=context,
                query=state["input_text"],
                history=_prior_turns(state, 6),
            ):
                chunks.append(chunk)
                await emit_token(config, "document_qa", chunk)
            reply = "".join(chunks).strip()
            return {
                "reply": reply,
                "status": "COMPLETED",
                "history": [{"role": "assistant", "content": reply}],
            }
        except Exception as exc:
            logger.exception("Document QA step failed")
            return {"reply": f"Belge sorusu yanıtlanamadı: {exc}", "status": "FAILED"}

    async def _run_chat(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        messages = [
            *_prior_turns(state, HISTORY_WINDOW),
            {"role": "user", "content": state["input_text"]},
        ]
        chunks: list[str] = []
        try:
            async for chunk in chat_agent.stream(messages=messages):
                chunks.append(chunk)
                await emit_token(config, "chat", chunk)
            reply = "".join(chunks).strip()
            return {
                "reply": reply,
                "status": "COMPLETED",
                "history": [{"role": "assistant", "content": reply}],
            }
        except Exception as exc:
            logger.exception("Chat step failed")
            return {"reply": f"Sohbet yanıtı üretilemedi: {exc}", "status": "FAILED"}

    async def execute_step_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Run the current plan step and advance the cursor."""
        idx = state.get("current_step_idx", 0)
        steps = state.get("plan_steps") or []
        if idx >= len(steps):
            return {}

        step = steps[idx].lower()
        label = STEP_LABELS.get(step, step.capitalize())
        logger.info("Executing plan step %d/%d: '%s'", idx + 1, len(steps), step)

        updates: dict[str, Any] = {"current_step_idx": idx + 1}
        cached = state.get("cached_document") or {}

        # Seed the classification from cache when the plan skips the analysis
        # step but a later step needs its output. Written into the returned
        # update rather than assigned onto `state`, which LangGraph does not
        # support and which silently lost the value on the next superstep.
        classification = state.get("classification_result") or {}
        if not classification and cached.get("analysis"):
            classification = cached["analysis"]
            updates["classification_result"] = classification

        failed_dependency = _dependency_failed(step, state, updates)
        if failed_dependency is not None:
            reason = (
                f"'{STEP_LABELS.get(failed_dependency, failed_dependency)}' adımı "
                "başarısız olduğu için bu adım atlandı."
            )
            logger.warning("Skipping plan step '%s': %s", step, reason)
            await emit_node_skipped(config, step, label, reason)
            updates[f"{step}_result"] = {"status": "SKIPPED", "reason": reason}
            if idx + 1 >= len(steps):
                updates["final_output"] = _compile_final_output(state, updates)
            return updates

        await emit_node_start(
            config, step, label, STEP_MESSAGES.get(step, f"{label} yürütülüyor...")
        )

        try:
            if step == "classification":
                classification = await _run_classification(state, config)
                updates["classification_result"] = classification

            elif step == "rag":
                query = classification.get("summary") or state["input_text"]
                updates["rag_result"] = await rag_graph.ainvoke(
                    {"original_query": query, "attempts": 0},
                    config=child_config(config),
                )

            elif step == "draft":
                updates["draft_result"] = await _run_draft(state, classification, config)

            elif step == "routing":
                draft_result = updates.get("draft_result") or state.get("draft_result") or {}
                score = draft_result.get("confidence_score", 100.0)
                if draft_result.get("requires_human_approval"):
                    score = 0.0
                updates["routing_result"] = await routing_graph.ainvoke(
                    {"draft": draft_result.get("draft", ""), "confidence_score": score},
                    config=child_config(config),
                )

            elif step == "chat":
                updates["chat_result"] = await _run_chat(state, config)

            elif step == "document_qa":
                updates["document_qa_result"] = await _run_document_qa(
                    state, classification, config
                )

            else:
                logger.warning("Unknown workflow step skipped: %s", step)

        except (asyncio.CancelledError, GraphInterrupt):
            # A client disconnect or an interrupt() call anywhere in this
            # node's call tree must propagate, not be swallowed into a FAILED
            # result -- either would otherwise look exactly like an ordinary
            # step failure to the rest of the graph. No sub-graph calls
            # interrupt() today, but this node has a checkpointer attached
            # once one is configured, so a future one must not be silently
            # eaten here.
            raise
        except Exception as exc:
            logger.exception("Plan step '%s' failed", step)
            updates[f"{step}_result"] = {"status": "FAILED", "error": str(exc)}
            await emit_node_error(
                config, step, label, f"{label} sırasında bir hata oluştu.", detail=str(exc)
            )

        if idx + 1 >= len(steps):
            updates["final_output"] = _compile_final_output(state, updates)

        # The sub-graphs emit their own node_end events with richer payloads;
        # only announce completion here for steps that have none, and only
        # when the step didn't already report itself via emit_node_error above.
        if step in {"classification", "draft", "routing"}:
            pass
        elif updates.get(f"{step}_result", {}).get("status") == "FAILED":
            pass
        else:
            await emit_node_end(
                config, step, label, f"{label} tamamlandı.", updates.get(f"{step}_result", {})
            )

        return updates

    def _compile_final_output(
        state: PlanningState, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Assemble the response payload from state plus this step's updates."""

        def _pick(key: str) -> dict[str, Any]:
            return updates.get(key) or state.get(key) or {}

        draft_result = _pick("draft_result")
        draft_status = draft_result.get("status")
        final_status = (
            draft_status
            if draft_status
            in {
                "FAILED",
                "NEEDS_HUMAN_APPROVAL",
                "NEEDS_INPUT",
                "REVISE_REQUESTED",
                "REJECTED",
            }
            else "COMPLETED"
        )

        return {
            "status": final_status,
            "classification": _pick("classification_result"),
            "rag": _pick("rag_result"),
            "draft": draft_result,
            "routing": _pick("routing_result"),
            "chat": _pick("chat_result"),
            "document_qa": _pick("document_qa_result"),
        }

    async def human_gate_node(
        state: PlanningState, config: RunnableConfig
    ) -> dict[str, Any]:
        """Pause the run for a human answer, then apply it without regenerating.

        A separate node from ``executor`` on purpose: ``interrupt()`` replays
        its own node from the top on resume. Living here, resuming replays a
        few dict lookups; living inside ``execute_step_node`` (which is where
        the draft step itself runs), resuming would replay the entire ~30s
        draft generation the executor already committed to state.
        """
        draft_result = state.get("draft_result") or {}
        missing_information = draft_result.get("missing_information") or []
        kind = "missing_information" if missing_information else "draft_approval"

        payload = {
            "kind": kind,
            "questions": missing_information,
            "draft": draft_result.get("draft", ""),
            "verification": draft_result.get("verification", {}),
            "judge": draft_result.get("judge", {}),
            "combined_score": draft_result.get("combined_score"),
            "requires_human_approval": draft_result.get("requires_human_approval"),
        }
        # Deterministic, not a fresh uuid4: interrupt() re-executes everything
        # before it on resume, including this id's computation, and it must
        # come out identical both times for the frontend's dedup to work.
        interrupt_id = hashlib.sha256(
            f"{kind}:{draft_result.get('draft', '')}:{state.get('current_step_idx', 0)}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]

        HITL_INTERRUPTS.labels(kind=kind).inc()
        await emit_node_start(
            config,
            "human_gate",
            "İnsan Onayı",
            "Devam etmek için insan onayı/eksik bilgi bekleniyor...",
        )
        await emit_interrupt(config, kind=kind, interrupt_id=interrupt_id, payload=payload)
        answer = interrupt(payload)
        answer = answer if isinstance(answer, dict) else {}
        # Execution only reaches here after Command(resume=...) -- the gate is
        # now resolved, whatever the human decided.
        await emit_node_end(
            config, "human_gate", "İnsan Onayı", "İnsan yanıtı alındı, işleme devam ediliyor.", answer
        )

        if kind == "missing_information":
            filled_draft, residual = apply_answers(
                draft_result.get("draft", ""), answer.get("answers", {})
            )

            if residual:
                residual_questions = [
                    question
                    for question in missing_information
                    if question.get("key") in residual
                ]
                updated = {
                    **draft_result,
                    "draft": filled_draft,
                    "missing_information": residual_questions,
                    "status": "NEEDS_INPUT",
                }
                return {"draft_result": updated}

            report = verify_draft(
                filled_draft,
                source_document=draft_result.get("source_document", ""),
                context=draft_result.get("context", ""),
                classification=draft_result.get("classification") or {},
                instructions=draft_result.get("instructions", ""),
                strict=draft_result.get("correspondence_type") != "other_official",
            )
            status = "NEEDS_HUMAN_APPROVAL" if report.requires_human_approval else "COMPLETED"
            updated = {
                **draft_result,
                "draft": filled_draft,
                "confidence_score": report.confidence_score,
                "combined_score": report.confidence_score,
                "requires_human_approval": report.requires_human_approval,
                "verification": report.model_dump(),
                "evaluation_notes": report.evaluation_notes,
                "missing_information": [],
                "status": status,
            }
            return {"draft_result": updated}

        # draft_approval
        action = answer.get("action")
        if action == "revise":
            note = (answer.get("instructions") or "").strip()
            existing = draft_result.get("instructions", "")
            updated = {
                **draft_result,
                "instructions": f"{existing}\n\nEk talimat (insan geri bildirimi): {note}".strip(),
                "status": "REVISE_REQUESTED",
            }
            updates = {"draft_result": updated}
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        if action == "reject":
            updated = {**draft_result, "status": "REJECTED"}
            updates = {"draft_result": updated}
            updates["final_output"] = _compile_final_output(state, updates)
            return updates

        # Default: approve. Falls through to routing via route_after_gate.
        updated = {
            **draft_result,
            "status": "APPROVED",
            "approved_by": answer.get("user_id"),
        }
        return {"draft_result": updated}

    def route_after_step(state: PlanningState) -> str:
        idx = state.get("current_step_idx", 0)
        steps = state.get("plan_steps") or []

        if has_checkpointer and idx > 0:
            just_ran = steps[idx - 1].lower()
            if just_ran == "draft":
                draft_result = state.get("draft_result") or {}
                draft_status = draft_result.get("status")
                if draft_status == "NEEDS_INPUT":
                    return "human_gate"
                if (
                    draft_status == "NEEDS_HUMAN_APPROVAL"
                    and settings.HITL_APPROVAL_GATE_ENABLED
                ):
                    return "human_gate"

        return "continue" if idx < len(steps) else "end"

    def route_after_gate(state: PlanningState) -> str:
        draft_result = state.get("draft_result") or {}
        status = draft_result.get("status")
        if status == "NEEDS_INPUT":
            return "human_gate"
        if status in {"REVISE_REQUESTED", "REJECTED"}:
            return "end"
        return "continue"

    builder = StateGraph(PlanningState)
    builder.add_node("planning", planning_node)
    builder.add_node("executor", execute_step_node)
    builder.add_node("human_gate", human_gate_node)

    builder.add_edge(START, "planning")
    builder.add_edge("planning", "executor")
    builder.add_conditional_edges(
        "executor",
        route_after_step,
        {"continue": "executor", "human_gate": "human_gate", "end": END},
    )
    builder.add_conditional_edges(
        "human_gate",
        route_after_gate,
        {"human_gate": "human_gate", "continue": "executor", "end": END},
    )

    return builder.compile(checkpointer=checkpointer)
