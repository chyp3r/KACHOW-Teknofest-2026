import asyncio
import logging
from typing import Any

from app.api.exceptions.ai_error import AIException
from app.core.constants import AI_WORKFLOW_TIMEOUT_SECONDS
from app.domains.chat.schema.chat_schema import ChatMessageRequest, ChatMessageResponse

logger = logging.getLogger(__name__)

class ChatService:
    """Service for orchestrating chat and AI workflows (Task 3)."""

    def __init__(
        self,
        planning_graph: Any,
    ) -> None:
        self.planning_graph = planning_graph

    async def handle_message(self, request: ChatMessageRequest) -> ChatMessageResponse:
        """Process a user message through the Master Planning Graph."""
        
        try:
            state = await asyncio.wait_for(
                self.planning_graph.ainvoke(
                    {
                        "input_text": request.message,
                        "document_id": request.document_id,
                    },
                    config=self._trace_config()
                ),
                timeout=AI_WORKFLOW_TIMEOUT_SECONDS * 2.0,  # Longer timeout for orchestration
            )
        except asyncio.TimeoutError as e:
            raise AIException(
                message="Sohbet işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": AI_WORKFLOW_TIMEOUT_SECONDS * 2.0},
            ) from e
        except Exception as e:
            logger.exception("Orchestration workflow failed")
            raise AIException(
                message="İş akışı sırasında bir hata oluştu.",
                details={"reason": str(e)},
            ) from e

        final_output = state.get("final_output", {})
        status = final_output.get("status", "FAILED")
        
        # Determine the reply text to show to the user
        chat_res = final_output.get("chat", {})
        draft_res = final_output.get("draft", {})
        rag_res = final_output.get("rag", {})
        document_qa_res = final_output.get("document_qa", {})
        
        reply = "İşleminiz tamamlandı."
        
        if document_qa_res and document_qa_res.get("reply"):
            reply = document_qa_res.get("reply")
        elif chat_res and chat_res.get("reply"):
            # Plain conversation reply
            reply = chat_res.get("reply")
        elif draft_res and draft_res.get("draft"):
            # Generated a draft
            reply = f"Resmi yazı taslağınız hazırlandı.\n\n{draft_res.get('draft')}"
        elif rag_res and rag_res.get("context"):
            # Retrieved context but no draft
            reply = "Mevzuattan ilgili bilgiler bulundu, ancak taslak oluşturulamadı."
            
        return ChatMessageResponse(
            reply=reply,
            workflow_status=status,
            details=final_output
        )

    @staticmethod
    def _trace_config() -> dict[str, Any]:
        try:
            from app.observability.tracer import get_langfuse_callback
            handler = get_langfuse_callback()
        except Exception:
            return {}
        return {"callbacks": [handler]} if handler else {}
