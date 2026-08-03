import asyncio
import logging
from typing import Any, AsyncIterator, Callable, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.reasoning_levels import get_reasoning_level_preset
from app.api.exceptions.ai_error import AIException
from app.core.constants import AI_WORKFLOW_TIMEOUT_SECONDS
from app.domains.chat.schema.chat_schema import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatResumeRequest,
)
from app.domains.drafts.repository import DraftRepository
from app.infrastructure.database.session import AsyncSessionLocal
from app.observability.ai_metrics import HITL_RESUMES

logger = logging.getLogger(__name__)

#: The orchestrated flow runs several sub-graphs, so it gets a longer budget
#: than a single analysis pass.
ORCHESTRATION_TIMEOUT_SECONDS = AI_WORKFLOW_TIMEOUT_SECONDS * 2

DEFAULT_REPLY = "İşleminiz tamamlandı."
INTERRUPTED_REPLY = "Devam etmek için ek bilgiye veya onayınıza ihtiyaç var."


class ChatService:
    """Orchestrates chat and AI workflows through the master planning graph."""

    def __init__(
        self,
        planning_graph: Any,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
    ) -> None:
        """Initialise the service.

        Args:
            planning_graph: The compiled master planning workflow.
            session_factory: Builds a DB session for draft persistence. A
                constructor param (default ``AsyncSessionLocal``) rather than
                a ``Depends(get_db)`` parameter on each call, because this
                service's streaming methods run their graph invocation in a
                background ``asyncio.create_task`` -- a request-scoped
                session would already be closed by the time that task reads
                or writes the drafts table.
        """
        self.planning_graph = planning_graph
        self._session_factory = session_factory

    async def handle_message(
        self, request: ChatMessageRequest, user_id: Optional[str] = None
    ) -> ChatMessageResponse:
        """Process a user message and return the completed (or paused) result.

        Args:
            request: The chat request.
            user_id: The authenticated user, when auth is enabled -- recorded
                on any draft version this turn produces.

        Returns:
            The orchestrated response.

        Raises:
            AIException: If the workflow fails or exceeds its timeout.
        """
        thread_id = self._thread_id(request.session_id)
        config = self._trace_config(thread_id)
        state = await self._invoke(request, config=config)
        return await self._response_from_state(
            state, config, thread_id, user_id=user_id, document_id=request.document_id
        )

    async def handle_message_stream(
        self, request: ChatMessageRequest, user_id: Optional[str] = None
    ) -> AsyncIterator[dict[str, Any]]:
        """Process a user message, yielding progress events as they happen.

        The worker task is cancelled if the consumer stops iterating. Previously
        the task was only awaited after the loop, so a client that disconnected
        mid-stream left the graph running -- holding the local model busy for a
        response nobody would receive.

        Args:
            request: The chat request.
            user_id: The authenticated user, when auth is enabled.

        Yields:
            Progress and result events. The first event is always ``session``,
            carrying the resolved ``thread_id`` -- generated server-side when
            the caller didn't supply one -- so the client can resume later.
        """
        thread_id = self._thread_id(request.session_id)
        yield {"event": "session", "thread_id": thread_id}

        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                config = self._trace_config(thread_id)
                config.setdefault("configurable", {})["status_queue"] = queue

                state = await self._invoke(request, config=config)
                await self._enqueue_terminal_event(
                    queue,
                    state,
                    config,
                    thread_id,
                    user_id=user_id,
                    document_id=request.document_id,
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
    ) -> ChatMessageResponse:
        """Resume a run paused at the human-in-the-loop gate and await its result.

        Args:
            session_id: The thread_id the paused run is waiting on.
            request: The human's answer/decision.
            user_id: The authenticated user, when auth is enabled.

        Returns:
            The orchestrated response, completed or paused again (e.g. when
            some missing-information answers were left blank).

        Raises:
            AIException: If resuming fails or exceeds its timeout.
        """
        from langgraph.types import Command

        HITL_RESUMES.labels(action=request.action).inc()
        config = self._trace_config(session_id)
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

        return await self._response_from_state(
            state, config, session_id, user_id=user_id, document_id=None
        )

    async def resume_stream(
        self,
        session_id: str,
        request: ChatResumeRequest,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume a paused run, yielding progress events as they happen.

        Same worker/queue shape as :meth:`handle_message_stream`; the only
        difference is that the graph resumes from its checkpoint via
        ``Command(resume=...)`` instead of starting a fresh run.

        Args:
            session_id: The thread_id the paused run is waiting on.
            request: The human's answer/decision.
            user_id: The authenticated user, when auth is enabled.

        Yields:
            Progress and result events.
        """
        from langgraph.types import Command

        HITL_RESUMES.labels(action=request.action).inc()
        timeout = ORCHESTRATION_TIMEOUT_SECONDS * get_reasoning_level_preset(
            request.reasoning_level
        ).timeout_multiplier
        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                config = self._trace_config(session_id)
                config.setdefault("configurable", {})["status_queue"] = queue

                state = await asyncio.wait_for(
                    self.planning_graph.ainvoke(
                        Command(resume=self._resume_payload(request)), config=config
                    ),
                    timeout=timeout,
                )
                await self._enqueue_terminal_event(
                    queue, state, config, session_id, user_id=user_id, document_id=None
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

    async def get_session_state(self, session_id: str) -> dict[str, Any]:
        """Report whether a session is idle, running, or paused on an interrupt.

        Args:
            session_id: The thread_id to inspect.

        Returns:
            ``{"status": "interrupted", "interrupt": {...}}`` when paused,
            ``{"status": "idle", "interrupt": None}`` otherwise (including
            when no checkpointer is configured, in which case a session can
            never be found paused).
        """
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
        self, request: ChatMessageRequest, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Run the planning graph under a timeout.

        Args:
            request: The chat request.
            config: The LangGraph runnable config.

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

        thread_id = (config.get("configurable") or {}).get("thread_id")
        last_draft = await self._fetch_last_draft(thread_id) if thread_id else {}

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
                        "last_draft": last_draft,
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
        *,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> None:
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
            user_id: The authenticated user, when auth is enabled.
            document_id: The document attached to *this* request, if any.
        """
        if await self._is_paused(config):
            logger.info("Session %s paused at a human-in-the-loop gate.", thread_id)
            return

        final_output = state.get("final_output", {}) or {}
        await self._persist_draft_version(
            session_id=thread_id,
            final_output=final_output,
            user_id=user_id,
            document_id=document_id,
        )
        await queue.put(
            {
                "event": "final_result",
                "reply": self._select_reply(final_output),
                "workflow_status": final_output.get("status", "FAILED"),
                "details": final_output,
            }
        )

    async def _response_from_state(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        thread_id: str,
        *,
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
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
        await self._persist_draft_version(
            session_id=thread_id,
            final_output=final_output,
            user_id=user_id,
            document_id=document_id,
        )
        return ChatMessageResponse(
            reply=self._select_reply(final_output),
            workflow_status=final_output.get("status", "FAILED"),
            session_id=thread_id,
            details=final_output,
        )

    async def _fetch_last_draft(self, session_id: str) -> dict[str, Any]:
        """The conversation's current draft, as a plain dict for graph state.

        Args:
            session_id: The checkpointer thread_id (== drafts.session_id).

        Returns:
            The latest ``DraftModel``'s fields, or ``{}`` when the
            conversation has no draft yet. Never raises: a DB outage here
            must degrade to "no draft to revise", not fail the whole turn.
        """
        try:
            async with self._session_factory() as db:
                draft = await DraftRepository(db).get_latest_for_session(session_id)
        except Exception:
            logger.exception("Failed to fetch last draft for session %s", session_id)
            return {}

        if draft is None:
            return {}
        return {
            "id": draft.id,
            "content": draft.content,
            "document_id": draft.document_id,
            "correspondence_type": draft.correspondence_type,
            "routed_unit": draft.routed_unit,
            "status": draft.status,
            "confidence_score": draft.confidence_score,
        }

    async def _persist_draft_version(
        self,
        *,
        session_id: str,
        final_output: dict[str, Any],
        user_id: Optional[str],
        document_id: Optional[str],
    ) -> None:
        """Append a new draft version when this turn produced or edited one.

        Skipped when the draft's content is unchanged from the latest stored
        version (e.g. a plain ``approve`` on the human-in-the-loop gate) --
        otherwise every approval of an already-persisted draft would mint a
        redundant version. Never raises: a persistence failure here must not
        fail a turn whose actual workflow already completed successfully.

        Args:
            session_id: The checkpointer thread_id (== drafts.session_id).
            final_output: The compiled workflow result for this turn.
            user_id: The authenticated user, when auth is enabled.
            document_id: The document attached to *this* request, if any --
                falls back to the previous version's document_id when this
                turn is a revision with nothing newly attached.
        """
        draft_result = final_output.get("draft") or {}
        content = draft_result.get("draft")
        if not content:
            return

        try:
            async with self._session_factory() as db:
                repo = DraftRepository(db)
                latest = await repo.get_latest_for_session(session_id)
                if latest is not None and latest.content == content:
                    return

                routing_result = final_output.get("routing") or {}
                status = draft_result.get("status")
                await repo.create_version(
                    session_id=session_id,
                    content=content,
                    user_id=user_id,
                    document_id=document_id or (latest.document_id if latest else None),
                    correspondence_type=draft_result.get("correspondence_type"),
                    routed_unit=routing_result.get("routed_unit"),
                    status=str(status) if status else None,
                    confidence_score=draft_result.get("confidence_score"),
                    instructions=draft_result.get("instructions"),
                    parent=latest,
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to persist draft version for session %s", session_id)

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
            "reasoning_level": (
                request.reasoning_level.value if request.reasoning_level else None
            ),
        }

    @staticmethod
    def _thread_id(session_id: Optional[str]) -> str:
        """Resolve the checkpointer thread_id for a request.

        Args:
            session_id: The client-supplied session id, if any.

        Returns:
            ``session_id`` unchanged, or a fresh server-generated id.
        """
        return session_id or f"anon:{uuid4()}"

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
            routing = final_output.get("routing") or {}
            parts = [f"Resmî yazı taslağınız hazırlandı.\n\n{draft['draft']}"]
            if routing.get("routed_unit"):
                parts.append(f"\n\n**Önerilen Birim:** {routing['routed_unit']}")
            if draft.get("status") == "REJECTED":
                parts.append("\n\n_Bu taslak reddedildi._")
            elif draft.get("status") == "REVISE_REQUESTED":
                parts.append("\n\n_Bu taslak için revizyon talep edildi._")
            elif draft.get("requires_human_approval"):
                parts.append(
                    "\n\n_Bu taslak insan onayı gerektiriyor: "
                    f"{draft.get('evaluation_notes', '')}_"
                )
            return "".join(parts)

        if draft.get("error"):
            return f"Taslak oluşturulamadı: {draft['error']}"

        classification = final_output.get("classification") or {}
        if classification.get("summary"):
            return (
                f"Evrak analizi tamamlandı.\n\n"
                f"**Tür:** {classification.get('document_type_label', 'Belirlenemedi')}\n\n"
                f"**Özet:** {classification['summary']}"
            )

        if (final_output.get("rag") or {}).get("context"):
            return "Mevzuattan ilgili bilgiler bulundu, ancak taslak oluşturulamadı."

        return DEFAULT_REPLY

    @staticmethod
    def _trace_config(thread_id: str) -> dict[str, Any]:
        """Build the LangGraph config: thread_id plus Langfuse tracing when available.

        Args:
            thread_id: The checkpointer thread id for this session.

        Returns:
            A config dict with ``configurable.thread_id`` always set, and
            ``callbacks`` present only when tracing is available.
        """
        try:
            from app.observability.tracer import build_trace_config

            return build_trace_config(thread_id=thread_id)
        except Exception:
            logger.debug("Langfuse tracing unavailable; continuing without it.")
            return {"configurable": {"thread_id": thread_id}}
