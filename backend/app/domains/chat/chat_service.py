import asyncio
import logging
from typing import Any, AsyncIterator, Optional
from uuid import uuid4

from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.workflows.events import emit_reply_stream
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.authorization import AuthorizationException
from app.core.config import settings
from app.domains.chat import chat_recorder
from app.domains.drafts import draft_recorder
from app.domains.chat.schema.chat_schema import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatResumeRequest,
)
from app.observability.ai_metrics import HITL_RESUMES

logger = logging.getLogger(__name__)

#: The orchestrated flow runs several sub-graphs, so it gets a longer budget
#: than a single analysis pass.
ORCHESTRATION_TIMEOUT_SECONDS = settings.AI_WORKFLOW_TIMEOUT_SECONDS * 2

DEFAULT_REPLY = "İşleminiz tamamlandı."
INTERRUPTED_REPLY = "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var."


class ChatService:
    """Orchestrates chat and AI workflows through the master planning graph."""

    def __init__(self, planning_graph: Any) -> None:
        """Initialise the service.

        Args:
            planning_graph: The compiled master planning workflow.
        """
        self.planning_graph = planning_graph

    async def handle_message(
        self,
        request: ChatMessageRequest,
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageResponse:
        """Process a user message and return the completed (or paused) result.

        Args:
            request: The chat request.
            user_id: The authenticated caller's id, when ``REQUIRE_AUTH`` is
                on -- folded into the thread_id so one user cannot address
                another's thread by guessing/reusing its session_id. ``None``
                in the open demo/dev path, unchanged from before this
                existed.
            requester_clearance: The authenticated caller's resolved
                ``SensitivityLevel.value`` (see
                ``app.core.permissions.role_checker.clearance_for``), when
                known. ``None`` in the open demo/dev path.
            company_id: The authenticated caller's tenant -- carried into
                the graph's own state (``PlanningState.company_id``) so the
                run/draft/guardrail recorders can attribute their writes to
                a company, the same way ``user_id`` already is.

        Returns:
            The orchestrated response.

        Raises:
            AIException: If the workflow fails or exceeds its timeout.
        """
        thread_id = self._thread_id(request.session_id, user_id)
        config = self._trace_config(thread_id, user_id, company_id)
        state = await self._invoke(
            request,
            config=config,
            user_id=user_id,
            requester_clearance=requester_clearance,
            company_id=company_id,
        )
        response = await self._response_from_state(
            state, config, thread_id, user_id=user_id, document_id=request.document_id, company_id=company_id
        )
        await chat_recorder.record_turn(
            thread_id=thread_id,
            user_id=user_id,
            document_id=request.document_id,
            user_message=request.message,
            reply=response.reply,
            workflow_status=response.workflow_status,
            details=response.details,
            company_id=company_id,
        )
        return response

    async def handle_message_stream(
        self,
        request: ChatMessageRequest,
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Process a user message, yielding progress events as they happen.

        The worker task is cancelled if the consumer stops iterating. Previously
        the task was only awaited after the loop, so a client that disconnected
        mid-stream left the graph running -- holding the local model busy for a
        response nobody would receive.

        Args:
            request: The chat request.
            user_id: See :meth:`handle_message`.
            requester_clearance: See :meth:`handle_message`.
            company_id: See :meth:`handle_message`.

        Yields:
            Progress and result events. The first event is always ``session``,
            carrying the resolved ``thread_id`` -- generated server-side when
            the caller didn't supply one -- so the client can resume later.
        """
        thread_id = self._thread_id(request.session_id, user_id)
        yield {"event": "session", "thread_id": thread_id}

        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                config = self._trace_config(thread_id, user_id, company_id)
                config.setdefault("configurable", {})["status_queue"] = queue

                state = await self._invoke(
                    request,
                    config=config,
                    user_id=user_id,
                    requester_clearance=requester_clearance,
                    company_id=company_id,
                )
                reply, workflow_status, details = await self._enqueue_terminal_event(
                    queue,
                    state,
                    config,
                    thread_id,
                    user_id=user_id,
                    document_id=request.document_id,
                    company_id=company_id,
                )
                await chat_recorder.record_turn(
                    thread_id=thread_id,
                    user_id=user_id,
                    document_id=request.document_id,
                    user_message=request.message,
                    reply=reply,
                    workflow_status=workflow_status,
                    details=details,
                    company_id=company_id,
                )
            except asyncio.CancelledError:
                raise
            except AIException as exc:
                await queue.put(
                    {"event": "error", "message": exc.message, "details": exc.details}
                )
            except Exception as exc:
                logger.exception("Streaming workflow failed")
                await queue.put(
                    {
                        "event": "error",
                        "message": "İş akışı sırasında bir hata oluştu.",
                        "details": str(exc),
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_graph())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            # Surface a crash in the worker rather than swallowing it, but never
            # let teardown of a cancelled task raise out of the generator.
            await asyncio.gather(task, return_exceptions=True)

    async def resume(
        self,
        session_id: str,
        request: ChatResumeRequest,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageResponse:
        """Resume a run paused at the human-in-the-loop gate and await its result.

        Args:
            session_id: The thread_id the paused run is waiting on.
            request: The human's answer/decision.
            user_id: The authenticated caller's id, when ``REQUIRE_AUTH`` is
                on. Must match the user_id the thread was created under (see
                :meth:`_thread_id`), or the resume is refused -- otherwise an
                authenticated caller could resume another user's paused run
                simply by knowing/guessing its session_id.
            company_id: The authenticated caller's tenant, for the recorder
                write below -- the graph's own ``company_id`` state field is
                already set from the original ``handle_message`` invocation
                and survives the checkpointer resume unchanged, so this is
                only needed here for :func:`chat_recorder.record_turn`.

        Returns:
            The orchestrated response, completed or paused again (e.g. when
            some missing-information answers were left blank).

        Raises:
            AIException: If resuming fails or exceeds its timeout.
            AuthorizationException: If ``session_id`` belongs to a different
                user than ``user_id``.
        """
        from langgraph.types import Command

        self._verify_thread_ownership(session_id, user_id)
        HITL_RESUMES.labels(action=request.action).inc()
        config = self._trace_config(session_id, user_id, company_id)
        # No explicit escalation on this resume -> preset resolves to
        # BALANCED (multiplier 1.0), leaving today's fixed timeout unchanged.
        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        try:
            state = await asyncio.wait_for(
                self.planning_graph.ainvoke(
                    Command(resume=self._resume_payload(request)), config=config
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Devam işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": timeout},
            ) from exc
        except Exception as exc:
            logger.exception("Resume failed")
            raise AIException(
                message="Devam işlemi sırasında bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

        response = await self._response_from_state(
            state, config, session_id, user_id=user_id, document_id=None, company_id=company_id
        )
        await chat_recorder.record_turn(
            thread_id=session_id,
            user_id=user_id,
            document_id=None,
            user_message=self._resume_summary(request),
            reply=response.reply,
            workflow_status=response.workflow_status,
            details=response.details,
            company_id=company_id,
        )
        return response

    async def resume_stream(
        self,
        session_id: str,
        request: ChatResumeRequest,
        user_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume a paused run, yielding progress events as they happen.

        Same worker/queue shape as :meth:`handle_message_stream`; the only
        difference is that the graph resumes from its checkpoint via
        ``Command(resume=...)`` instead of starting a fresh run.

        Args:
            session_id: The thread_id the paused run is waiting on.
            request: The human's answer/decision.
            user_id: See :meth:`resume`.
            company_id: See :meth:`resume`.

        Yields:
            Progress and result events.

        Raises:
            AuthorizationException: If ``session_id`` belongs to a different
                user than ``user_id``.
        """
        from langgraph.types import Command

        self._verify_thread_ownership(session_id, user_id)
        HITL_RESUMES.labels(action=request.action).inc()
        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                config = self._trace_config(session_id, user_id, company_id)
                config.setdefault("configurable", {})["status_queue"] = queue

                state = await asyncio.wait_for(
                    self.planning_graph.ainvoke(
                        Command(resume=self._resume_payload(request)), config=config
                    ),
                    timeout=timeout,
                )
                reply, workflow_status, details = await self._enqueue_terminal_event(
                    queue, state, config, session_id, user_id=user_id, document_id=None, company_id=company_id
                )
                await chat_recorder.record_turn(
                    thread_id=session_id,
                    user_id=user_id,
                    document_id=None,
                    user_message=self._resume_summary(request),
                    reply=reply,
                    workflow_status=workflow_status,
                    details=details,
                    company_id=company_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Streaming resume failed")
                await queue.put(
                    {
                        "event": "error",
                        "message": "Devam işlemi sırasında bir hata oluştu.",
                        "details": str(exc),
                    }
                )
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_graph())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def get_session_state(
        self, session_id: str, user_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Report whether a session is idle, running, or paused on an interrupt.

        Args:
            session_id: The thread_id to inspect.
            user_id: See :meth:`resume`.

        Returns:
            ``{"status": "interrupted", "interrupt": {...}}`` when paused,
            ``{"status": "idle", "interrupt": None}`` otherwise (including
            when no checkpointer is configured, in which case a session can
            never be found paused).

        Raises:
            AuthorizationException: If ``session_id`` belongs to a different
                user than ``user_id``.
        """
        self._verify_thread_ownership(session_id, user_id)
        config = self._trace_config(session_id)
        try:
            snapshot = await self.planning_graph.aget_state(config)
        except Exception:
            return {"status": "idle", "interrupt": None}

        if not snapshot.next:
            return {"status": "idle", "interrupt": None}

        interrupt_payload = self._extract_interrupt(snapshot)
        if interrupt_payload is None:
            return {"status": "running", "interrupt": None}
        return {"status": "interrupted", "interrupt": interrupt_payload}

    async def _invoke(
        self,
        request: ChatMessageRequest,
        config: dict[str, Any],
        user_id: Optional[str] = None,
        requester_clearance: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run the planning graph under a timeout.

        Args:
            request: The chat request.
            config: The LangGraph runnable config.
            user_id: The authenticated caller's id, when known -- carried
                into the graph's own state (not just the thread_id prefix)
                so the run-recording audit trail (see
                app.observability.run_recorder) can attribute a run to a
                user without parsing it back out of thread_id.
            requester_clearance: The authenticated caller's resolved
                clearance, carried into the graph state the same way --
                read by _run_assist to gate document tool calls and the
                output guardrail. Set once here; persists across a later
                human-in-the-loop resume via the checkpointer, same as
                user_id/document_id.
            company_id: The authenticated caller's tenant, carried into
                ``PlanningState.company_id`` the same way -- read by every
                recorder call inside the planning graph (``start_run``,
                ``record_step``, ``end_run``, the output guardrail's
                ``record_event``) so their writes can be attributed to a
                company. Also persists across a checkpointer resume.

        Returns:
            The final (or paused) workflow state.

        Raises:
            AIException: On timeout, workflow failure, or when this session
                already has a pending human-in-the-loop interrupt -- starting
                a fresh run on a thread with an outstanding paused task is not
                a supported resume path; the caller must use ``/chat/resume``
                (or a new session_id) instead.
        """
        if await self._is_paused(config):
            thread_id = (config.get("configurable") or {}).get("thread_id")
            raise AIException(
                message=(
                    "Bu oturum bir insan onayı veya eksik bilgi talebi bekliyor. "
                    "Devam etmek için /chat/resume uç noktasını kullanın."
                ),
                details={"session_id": thread_id},
            )

        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        try:
            return await asyncio.wait_for(
                self.planning_graph.ainvoke(
                    {
                        "input_text": request.message,
                        "document_id": request.document_id,
                        "reasoning_level": request.reasoning_level.value,
                        "user_id": user_id,
                        "requester_clearance": requester_clearance,
                        "company_id": company_id,
                    },
                    config=config,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Sohbet işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": timeout},
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Orchestration workflow failed")
            raise AIException(
                message="İş akışı sırasında bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

    async def _enqueue_terminal_event(
        self,
        queue: "asyncio.Queue",
        state: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> tuple[str, str, dict[str, Any]]:
        """Push the run's closing event: ``final_result``, or nothing if paused.

        A paused run already pushed its own ``interrupt`` event from inside
        ``human_gate_node`` (via ``emit_interrupt``) at the moment it actually
        suspended -- pushing a second, synthetic one here would duplicate it,
        and pushing ``final_result`` would be actively wrong, since a paused
        run's ``final_output`` is still empty. This only determines whether to
        stay silent (paused) or announce completion.

        Args:
            queue: The SSE progress queue.
            state: The state ``ainvoke``/resume returned.
            config: The config used for that call, reused to check pause state.
            thread_id: The session's thread_id, for logging only.
            user_id: See :meth:`handle_message`; forwarded to
                :meth:`_maybe_record_draft`.
            document_id: The document attached to this turn, if any;
                forwarded to :meth:`_maybe_record_draft`.

        Returns:
            ``(reply, workflow_status, details)`` for this turn -- the same
            values pushed (or that would have been pushed) as the SSE event,
            handed back so the caller can persist the turn without
            re-deriving them (and without re-checking pause state a second
            time).
        """
        if await self._is_paused(config):
            logger.info("Session %s paused at a human-in-the-loop gate.", thread_id)
            snapshot = await self.planning_graph.aget_state(config)
            interrupt_payload = self._extract_interrupt(snapshot) or {}
            return INTERRUPTED_REPLY, "INTERRUPTED", {"interrupt": interrupt_payload}

        final_output = state.get("final_output", {}) or {}
        reply = self._select_reply(final_output)
        workflow_status = final_output.get("status", "FAILED")
        # The only text ever streamed to the client this turn -- see
        # emit_reply_stream's docstring. Streamed *before* final_result so
        # the chat bubble fills in live rather than the whole reply
        # appearing at once with the "typing" state ending abruptly.
        await emit_reply_stream(queue, reply)
        await queue.put(
            {
                "event": "final_result",
                "reply": reply,
                "workflow_status": workflow_status,
                "details": final_output,
            }
        )
        await self._maybe_record_draft(final_output, config, thread_id, user_id, document_id, company_id)
        return reply, workflow_status, final_output

    async def _response_from_state(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> ChatMessageResponse:
        """Build the non-streaming response, accounting for a paused run."""
        if await self._is_paused(config):
            snapshot = await self.planning_graph.aget_state(config)
            interrupt_payload = self._extract_interrupt(snapshot) or {}
            return ChatMessageResponse(
                reply=INTERRUPTED_REPLY,
                workflow_status="INTERRUPTED",
                session_id=thread_id,
                details={"interrupt": interrupt_payload},
            )

        final_output = state.get("final_output", {}) or {}
        await self._maybe_record_draft(final_output, config, thread_id, user_id, document_id, company_id)
        return ChatMessageResponse(
            reply=self._select_reply(final_output),
            workflow_status=final_output.get("status", "FAILED"),
            session_id=thread_id,
            details=final_output,
        )

    async def _maybe_record_draft(
        self,
        final_output: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        user_id: Optional[str],
        document_id: Optional[str],
        company_id: Optional[str] = None,
    ) -> None:
        """Persist a draft this turn produced or revised, if any.

        ``final_output["draft"]`` is ``PlanningState.draft_result`` -- the
        same shape ``app.domains.documents.draft_service.DraftService``
        builds ``DraftResponseSchema`` from for the direct-API path. A no-op
        when this turn's step wasn't drafting/revising (``draft_result`` is
        then ``{}``, so ``.get("draft")`` is falsy).
        """
        draft = final_output.get("draft") or {}
        content = draft.get("draft")
        if not content:
            return
        routing = final_output.get("routing") or {}
        draft_id = await draft_recorder.record_draft(
            user_id=user_id,
            company_id=company_id,
            session_id=thread_id,
            document_id=document_id,
            content=content,
            correspondence_type=draft.get("correspondence_type"),
            destination=routing.get("final_destination"),
            destination_justification=routing.get("justification"),
            status=draft.get("status"),
            confidence_score=draft.get("confidence_score"),
            requires_human_approval=draft.get("requires_human_approval"),
            attempts=draft.get("attempts"),
            verification=draft.get("verification"),
            judge=draft.get("judge"),
            missing_information=draft.get("missing_information"),
        )
        if draft_id:
            # Best-effort, same tolerance `_is_paused` already has for a
            # missing/unreachable checkpointer: `SessionFocus.active_draft_id`
            # is a convenience hint (see its own docstring), never load-bearing
            # -- the `propose_transfer` tool (`app.ai.tools.transfer_tools`)
            # falls back to `DraftRepository.get_latest_for_session` regardless.
            try:
                await self.planning_graph.aupdate_state(
                    config, {"focus": {"active_draft_id": draft_id}}
                )
            except Exception:
                logger.warning("Could not persist active_draft_id for thread %s", thread_id)

    async def _is_paused(self, config: dict[str, Any]) -> bool:
        """Whether the last graph call left the run suspended on an interrupt.

        Safe to call even without a checkpointer configured: ``aget_state``
        raises in that case, which this treats as "never paused" -- correct,
        since ``route_after_step`` only ever detours to ``human_gate`` when a
        checkpointer is present in the first place.
        """
        try:
            snapshot = await self.planning_graph.aget_state(config)
        except Exception:
            return False
        return bool(snapshot.next)

    @staticmethod
    def _extract_interrupt(snapshot: Any) -> Optional[dict[str, Any]]:
        """Pull the pending interrupt's payload out of a state snapshot."""
        for task in getattr(snapshot, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", None) or ()
            for item in task_interrupts:
                value = getattr(item, "value", item)
                if isinstance(value, dict):
                    return value
        return None

    @staticmethod
    def _resume_payload(request: ChatResumeRequest) -> dict[str, Any]:
        """Shape a ChatResumeRequest into the dict human_gate_node's interrupt() expects."""
        return {
            "action": request.action,
            "answers": request.answers,
            "instructions": request.instructions,
            "reason": request.reason,
            "reasoning_level": (
                request.reasoning_level.value if request.reasoning_level else None
            ),
        }

    @staticmethod
    def _resume_summary(request: ChatResumeRequest) -> str:
        """A human-readable stand-in for the user's turn on a HITL resume.

        ``ChatResumeRequest`` carries structured answers/an action, not free
        text like ``ChatMessageRequest.message`` -- this renders it into
        something a chat history view can show in place of a message bubble.
        """
        if request.action == "answer" and request.answers:
            return "; ".join(
                f"{key}: {', '.join(value) if isinstance(value, list) else value}"
                for key, value in request.answers.items()
            )
        if request.action == "reject" and request.reason:
            return f"reject: {request.reason}"
        if request.instructions:
            return f"{request.action}: {request.instructions}"
        return request.action

    @staticmethod
    def _thread_id(session_id: Optional[str], user_id: Optional[str] = None) -> str:
        """Resolve the checkpointer thread_id for a request.

        Before ``user_id`` existed, the thread_id *was* the client-supplied
        ``session_id`` -- any caller who knew or reused another caller's
        session_id could resume/read that thread. Folding the authenticated
        user's id into the prefix makes that structurally impossible once
        ``REQUIRE_AUTH`` is on: no session_id an attacker can pick or guess
        starts with a user_id they don't have.

        Args:
            session_id: The client-supplied session id, if any.
            user_id: The authenticated caller's id, when ``REQUIRE_AUTH`` is
                on. ``None`` in the open demo/dev path, which keeps today's
                behaviour unchanged.

        Returns:
            ``f"{user_id}:{session_id}"`` when authenticated, otherwise
            ``session_id`` unchanged or a fresh server-generated id.
        """
        if user_id:
            return f"{user_id}:{session_id or uuid4()}"
        return session_id or f"anon:{uuid4()}"

    @staticmethod
    def _owns_thread(thread_id: str, user_id: Optional[str]) -> bool:
        """Whether an authenticated caller may resume/inspect ``thread_id``.

        ``user_id=None`` (``REQUIRE_AUTH`` disabled) is always allowed --
        unauthenticated mode has no concept of "someone else's thread" to
        guard against, matching the open demo/dev behaviour everywhere else
        in this phase. An authenticated caller may only touch threads
        carrying its own user_id prefix, the one :meth:`_thread_id` itself
        stamped on when the thread was first created.
        """
        if user_id is None:
            return True
        return thread_id.startswith(f"{user_id}:")

    @classmethod
    def _verify_thread_ownership(cls, thread_id: str, user_id: Optional[str]) -> None:
        """Raise if ``user_id`` is not allowed to resume/inspect ``thread_id``."""
        if not cls._owns_thread(thread_id, user_id):
            raise AuthorizationException(message="Bu oturuma erişim izniniz yok.")

    @staticmethod
    def _select_reply(final_output: dict[str, Any]) -> str:
        """Pick the text shown to the user from the completed workflow output.

        Args:
            final_output: The compiled workflow result.

        Returns:
            The reply text.
        """
        assist = final_output.get("assist") or {}
        if assist.get("reply"):
            return assist["reply"]

        draft = final_output.get("draft") or {}
        if draft.get("draft"):
            # The reply is the draft text alone -- routing unit, confidence
            # score, approval/rejection notes and the changelog summary all
            # used to be appended here as free text, but they are structured
            # data the frontend already receives via this same
            # final_output (as ``details`` on the chat message: see
            # ChatMessageResponse.details / the "final_result" SSE event)
            # and renders as its own meta strip -- see
            # frontend DraftMetaStrip. A conflict finding was never folded
            # in here either, for the same reason (see
            # app.ai.workflows.revise_graph.audit_node's "notice" event):
            # a structured finding belongs in a dedicated surface, not
            # concatenated onto the answer.
            return f"Resmî yazı taslağınız hazırlandı.\n\n{draft['draft']}"

        if draft.get("error"):
            return f"Taslak oluşturulamadı: {draft['error']}"

        classification = final_output.get("classification") or {}
        if classification.get("summary"):
            return (
                f"Evrak analizi tamamlandı.\n\n"
                f"**Tür:** {classification.get('document_type_label', 'Belirlenemedi')}\n\n"
                f"**Özet:** {classification['summary']}"
            )

        return DEFAULT_REPLY

    @staticmethod
    def _trace_config(
        thread_id: str, user_id: Optional[str] = None, company_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Build the LangGraph config: thread_id plus Langfuse tracing when available.

        Args:
            thread_id: The checkpointer thread id for this session.
            user_id, company_id: Attached as Langfuse trace metadata (see
                ``app.observability.tracer.build_trace_config``) when known
                -- omitted (not fabricated) at call sites that don't have
                one in scope, e.g. ``get_session_state``.

        Returns:
            A config dict with ``configurable.thread_id`` always set, and
            ``callbacks`` present only when tracing is available.
        """
        try:
            from app.observability.tracer import build_trace_config, company_tags

            return build_trace_config(
                thread_id=thread_id,
                langfuse_user_id=user_id,
                langfuse_session_id=thread_id,
                langfuse_tags=company_tags(company_id),
            )
        except Exception:
            logger.debug("Langfuse tracing unavailable; continuing without it.")
            return {"configurable": {"thread_id": thread_id}}
