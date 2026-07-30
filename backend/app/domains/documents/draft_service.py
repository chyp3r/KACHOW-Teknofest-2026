import asyncio
import logging
from typing import Any

from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.constants import AI_WORKFLOW_TIMEOUT_SECONDS
from app.domains.documents.schema.document_schema import DraftRequestSchema, DraftResponseSchema
from app.infrastructure.extractors.base import BaseDocumentExtractor, DocumentExtractionError
from app.infrastructure.storage.base import BaseStorage

logger = logging.getLogger(__name__)

class DraftService:
    """Service for handling document drafting and department routing (Task 2)."""

    def __init__(
        self,
        storage: BaseStorage,
        extractor: BaseDocumentExtractor,
        draft_graph: Any,
        routing_graph: Any,
    ) -> None:
        self.storage = storage
        self.extractor = extractor
        self.draft_graph = draft_graph
        self.routing_graph = routing_graph

    async def generate_draft_and_route(self, request: DraftRequestSchema) -> DraftResponseSchema:
        """Execute the drafting and routing workflows sequentially."""
        
        # 1. Fetch raw document and extract text
        try:
            content_bytes = await self.storage.get_file(request.storage_path)
        except Exception as e:
            logger.error(f"Failed to fetch document from storage: {e}")
            raise ValidationException(
                message="Belirtilen evrak dosyası bulunamadı.", 
                details={"storage_path": request.storage_path}
            ) from e

        try:
            extracted = await self.extractor.extract(content_bytes, file_name=request.storage_path)
            source_document = extracted.text
        except DocumentExtractionError as e:
            raise ValidationException(
                message="Evrak metni çıkarılamadı.", 
                details={"reason": str(e)}
            ) from e

        # 2. Run drafting workflow
        # Build context from mevzuat_references to inform the WriterAgent
        mevzuat_refs = request.classification.get("mevzuat_references", [])
        context_lines = []
        for ref in mevzuat_refs:
            mevz = ref.get("mevzuat", "")
            desc = ref.get("aciklama", "")
            if mevz:
                context_lines.append(f"- {mevz}: {desc}")
        context_str = "\n".join(context_lines) if context_lines else ""

        try:
            draft_state = await asyncio.wait_for(
                self.draft_graph.ainvoke(
                    {
                        "source_document": source_document,
                        "classification": request.classification,
                        "context": context_str,
                        "instructions": request.instructions,
                        "correspondence_type": request.correspondence_type,
                    },
                    config=self._trace_config()
                ),
                timeout=AI_WORKFLOW_TIMEOUT_SECONDS * 1.5,
            )
        except asyncio.TimeoutError as e:
            raise AIException(
                message="Taslak üretimi zaman aşımına uğradı.",
                details={"timeout_seconds": AI_WORKFLOW_TIMEOUT_SECONDS * 1.5},
            ) from e
        except Exception as e:
            logger.exception("Drafting workflow failed")
            raise AIException(
                message="Taslak üretimi sırasında bir hata oluştu.",
                details={"reason": str(e)},
            ) from e

        if draft_state.get("status") == "FAILED":
            raise AIException(
                message="Taslak üretilemedi.",
                details={"error": draft_state.get("error")},
            )

        draft_content = draft_state.get("draft", "")
        confidence = draft_state.get("confidence_score", 0.0)

        # 3. Run routing workflow
        try:
            routing_state = await asyncio.wait_for(
                self.routing_graph.ainvoke(
                    {
                        "draft": draft_content,
                        "confidence_score": confidence,
                    },
                    config=self._trace_config()
                ),
                timeout=AI_WORKFLOW_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            raise AIException(
                message="Yönlendirme kararı zaman aşımına uğradı.",
                details={"timeout_seconds": AI_WORKFLOW_TIMEOUT_SECONDS},
            ) from e
        except Exception as e:
            logger.exception("Routing workflow failed")
            raise AIException(
                message="Yönlendirme sırasında bir hata oluştu.",
                details={"reason": str(e)},
            ) from e

        return DraftResponseSchema(
            draft=draft_content,
            confidence_score=confidence,
            requires_human_approval=draft_state.get("requires_human_approval", True),
            destination=routing_state.get("final_destination", "HumanApproval"),
            justification=routing_state.get("justification", "Yönlendirme kararı alınamadı.")
        )

    @staticmethod
    def _trace_config() -> dict[str, Any]:
        try:
            from app.observability.tracer import get_langfuse_callback
            handler = get_langfuse_callback()
        except Exception:
            return {}
        return {"callbacks": [handler]} if handler else {}
