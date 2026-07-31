import asyncio
import logging
from typing import Any, AsyncIterator

from app.api.exceptions.ai_error import AIException
from app.core.constants import AI_WORKFLOW_TIMEOUT_SECONDS
from app.domains.chat.schema.chat_schema import ChatMessageRequest, ChatMessageResponse

logger = logging.getLogger(__name__)

#: The orchestrated flow runs several sub-graphs, so it gets a longer budget
#: than a single analysis pass.
ORCHESTRATION_TIMEOUT_SECONDS = AI_WORKFLOW_TIMEOUT_SECONDS * 2

DEFAULT_REPLY = "İşleminiz tamamlandı."


class ChatService:
    """Orchestrates chat and AI workflows through the master planning graph."""

    def __init__(self, planning_graph: Any) -> None:
        """Initialise the service.

        Args:
            planning_graph: The compiled master planning workflow.
        """
        self.planning_graph = planning_graph

    async def handle_message(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """Process a user message and return the completed result.

        Args:
            request: The chat request.

        Returns:
            The orchestrated response.

        Raises:
            AIException: If the workflow fails or exceeds its timeout.
        """
        state = await self._invoke(request, config=self._trace_config())
        final_output = state.get("final_output", {}) or {}
        return ChatMessageResponse(
            reply=self._select_reply(final_output),
            workflow_status=final_output.get("status", "FAILED"),
            details=final_output,
        )

    async def handle_message_stream(
        self, request: ChatMessageRequest
    ) -> AsyncIterator[dict[str, Any]]:
        """Process a user message, yielding progress events as they happen.

        The worker task is cancelled if the consumer stops iterating. Previously
        the task was only awaited after the loop, so a client that disconnected
        mid-stream left the graph running -- holding the local model busy for a
        response nobody would receive.

        Args:
            request: The chat request.

        Yields:
            Progress and result events.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def run_graph() -> None:
            try:
                config = self._trace_config()
                config.setdefault("configurable", {})["status_queue"] = queue

                state = await self._invoke(request, config=config)
                final_output = state.get("final_output", {}) or {}
                await queue.put(
                    {
                        "event": "final_result",
                        "reply": self._select_reply(final_output),
                        "workflow_status": final_output.get("status", "FAILED"),
                        "details": final_output,
                    }
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

    async def _invoke(
        self, request: ChatMessageRequest, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Run the planning graph under a timeout.

        Args:
            request: The chat request.
            config: The LangGraph runnable config.

        Returns:
            The final workflow state.

        Raises:
            AIException: On timeout or workflow failure.
        """
        try:
            return await asyncio.wait_for(
                self.planning_graph.ainvoke(
                    {
                        "input_text": request.message,
                        "document_id": request.document_id,
                    },
                    config=config,
                ),
                timeout=ORCHESTRATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Sohbet işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": ORCHESTRATION_TIMEOUT_SECONDS},
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Orchestration workflow failed")
            raise AIException(
                message="İş akışı sırasında bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

    @staticmethod
    def _select_reply(final_output: dict[str, Any]) -> str:
        """Pick the text shown to the user from the completed workflow output.

        Args:
            final_output: The compiled workflow result.

        Returns:
            The reply text.
        """
        document_qa = final_output.get("document_qa") or {}
        if document_qa.get("reply"):
            return document_qa["reply"]

        chat = final_output.get("chat") or {}
        if chat.get("reply"):
            return chat["reply"]

        draft = final_output.get("draft") or {}
        if draft.get("draft"):
            routing = final_output.get("routing") or {}
            parts = [f"Resmî yazı taslağınız hazırlandı.\n\n{draft['draft']}"]
            if routing.get("routed_unit"):
                parts.append(f"\n\n**Önerilen Birim:** {routing['routed_unit']}")
            if draft.get("requires_human_approval"):
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
    def _trace_config() -> dict[str, Any]:
        """Build the LangGraph config, attaching Langfuse tracing when available.

        Returns:
            A config dict, without callbacks when tracing is unavailable.
        """
        try:
            from app.observability.tracer import get_langfuse_callback

            handler = get_langfuse_callback()
        except Exception:
            logger.debug("Langfuse tracing unavailable; continuing without it.")
            return {}
        return {"callbacks": [handler]} if handler else {}
