import asyncio
import logging
from typing import Any, Optional

from app.ai.guardrails.injection import scrub_extracted_text
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.workflows.dates import today_tr
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.config import settings
from app.domains.documents.schema.document_schema import DraftRequestSchema, DraftResponseSchema
from app.domains.drafts import draft_recorder
from app.domains.quotas.service import DRAFTS_METRIC, QuotaService
from app.infrastructure.extractors.base import BaseDocumentExtractor, DocumentExtractionError
from app.infrastructure.storage.base import BaseStorage

logger = logging.getLogger(__name__)

class DraftService:
    """Service for handling document drafting and department routing (Task 2).

    Only this direct `POST /documents/draft` path and `DraftShareService.
    respond`'s accept-fork are quota-gated today, not chat-originated draft
    generation -- see `QuotaService`'s module docstring for the token-quota
    equivalent of this same honesty, and `docs/api/root.md`/`analytics.md`
    for why: the chat flow only decides *whether* a turn drafts at all deep
    inside the compiled `planning_graph`, and this codebase's own layering
    rule (`app.ai.*` never imports `app.domains.*` -- see
    `app.domains.units.provider`'s docstring) means a DB-backed quota check
    cannot live at the point that decision is made without violating it,
    the same reason confidentiality clearance is kept out of the ABAC engine
    itself (see `app.core.authz.engine`'s module docstring).
    """

    def __init__(
        self,
        storage: BaseStorage,
        extractor: BaseDocumentExtractor,
        draft_graph: Any,
        routing_graph: Any,
        quota_service: Optional[QuotaService] = None,
    ) -> None:
        self.storage = storage
        self.extractor = extractor
        self.draft_graph = draft_graph
        self.routing_graph = routing_graph
        self.quota_service = quota_service

    async def generate_draft_and_route(
        self, request: DraftRequestSchema, user_id: str, company_id: str
    ) -> DraftResponseSchema:
        """Execute the drafting and routing workflows sequentially.

        Args:
            request: The drafting request.
            user_id: The authenticated caller's id -- attached to the
                persisted draft version (see
                ``app.domains.drafts.draft_recorder``).
            company_id: The authenticated caller's company -- scopes the
                unit list the routing workflow chooses from.
        """
        if self.quota_service is not None:
            await self.quota_service.check_and_increment(company_id, DRAFTS_METRIC)


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
            source_document, scrubbed_markers = scrub_extracted_text(extracted.text)
            if scrubbed_markers:
                logger.warning(
                    "Scrubbed possible prompt injection from %s: %s",
                    request.storage_path,
                    scrubbed_markers,
                )
        except DocumentExtractionError as e:
            raise ValidationException(
                message="Evrak metni çıkarılamadı.",
                details={"reason": str(e)}
            ) from e

        # 2. Run drafting workflow
        # Build context from mevzuat_references to inform the WriterAgent
        context_lines = [
            f"- {ref.mevzuat}: {ref.aciklama}"
            for ref in request.classification.mevzuat_references
            if ref.mevzuat
        ]
        context_str = "\n".join(context_lines) if context_lines else ""

        # draft_graph's internal helpers (_build_brief, verify_draft, ...) treat
        # classification as a plain dict; the typed DraftClassificationSchema is
        # the boundary validation, not the graph's internal representation.
        classification_dict = request.classification.model_dump(mode="json")

        draft_timeout = (
            settings.AI_WORKFLOW_TIMEOUT_SECONDS
            * 1.5
            * get_reasoning_level_preset(request.reasoning_level).timeout_multiplier
        )
        try:
            draft_state = await asyncio.wait_for(
                self.draft_graph.ainvoke(
                    {
                        "source_document": source_document,
                        "classification": classification_dict,
                        "context": context_str,
                        "instructions": request.instructions,
                        "correspondence_type": (
                            request.correspondence_type.value
                            if request.correspondence_type
                            else None
                        ),
                        "reasoning_level": request.reasoning_level.value,
                        "today": today_tr(),
                    },
                    config=self._trace_config(user_id, company_id)
                ),
                timeout=draft_timeout,
            )
        except asyncio.TimeoutError as e:
            raise AIException(
                message="Taslak üretimi zaman aşımına uğradı.",
                details={"timeout_seconds": draft_timeout},
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
        missing_information = draft_state.get("missing_information") or []
        common_fields = dict(
            draft=draft_content,
            confidence_score=confidence,
            requires_human_approval=draft_state.get("requires_human_approval", True),
            attempts=draft_state.get("attempts", 1),
            verification=draft_state.get("verification", {}),
            judge=draft_state.get("judge", {}),
            missing_information=missing_information,
            applied_rules=draft_state.get("applied_rules", []),
        )
        # DraftModel.verification has no dedicated applied_rules column (a
        # JSON blob already, no migration needed) -- folded in here so the
        # persisted record carries the full auditable score breakdown, not
        # just the response schema's own top-level field.
        verification_for_storage = {
            **common_fields["verification"],
            "applied_rules": common_fields["applied_rules"],
        }

        # This endpoint has no session/interrupt mechanism of its own (that's
        # the chat path's job via /chat/resume) -- a draft still carrying
        # unfilled placeholders is reported as-is rather than routed, since
        # routing a demonstrably incomplete draft to a department is worse
        # than not routing it at all.
        if missing_information:
            draft_id = await draft_recorder.record_draft(
                user_id=user_id,
                company_id=company_id,
                session_id=None,
                document_id=request.storage_path,
                content=draft_content,
                correspondence_type=(
                    request.correspondence_type.value if request.correspondence_type else None
                ),
                destination="",
                status=draft_state.get("status"),
                confidence_score=confidence,
                requires_human_approval=common_fields["requires_human_approval"],
                attempts=common_fields["attempts"],
                verification=verification_for_storage,
                judge=common_fields["judge"],
                missing_information=missing_information,
                instructions=request.instructions,
            )
            return DraftResponseSchema(
                **common_fields,
                draft_id=draft_id or "",
                destination="",
                justification="Taslak eksik bilgi içeriyor; birim yönlendirmesi yapılmadı.",
            )

        # 3. Run routing workflow
        try:
            routing_state = await asyncio.wait_for(
                self.routing_graph.ainvoke(
                    {
                        "draft": draft_content,
                        "confidence_score": confidence,
                        "company_id": company_id,
                    },
                    config=self._trace_config(user_id, company_id)
                ),
                timeout=settings.AI_WORKFLOW_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as e:
            raise AIException(
                message="Yönlendirme kararı zaman aşımına uğradı.",
                details={"timeout_seconds": settings.AI_WORKFLOW_TIMEOUT_SECONDS},
            ) from e
        except Exception as e:
            logger.exception("Routing workflow failed")
            raise AIException(
                message="Yönlendirme sırasında bir hata oluştu.",
                details={"reason": str(e)},
            ) from e

        destination = routing_state.get("final_destination") or ""
        # Routing could not confidently assign a unit (empty draft, low
        # score, an LLM failure, or a hallucinated unit name) -- same flag
        # the draft-quality gate above already uses, OR'd in rather than
        # overwritten, since either source is a legitimate reason a human
        # needs to look at this draft before it goes anywhere.
        common_fields["requires_human_approval"] = common_fields[
            "requires_human_approval"
        ] or routing_state.get("requires_human_approval", False)
        draft_id = await draft_recorder.record_draft(
            user_id=user_id,
            company_id=company_id,
            session_id=None,
            document_id=request.storage_path,
            content=draft_content,
            correspondence_type=(
                request.correspondence_type.value if request.correspondence_type else None
            ),
            destination=destination,
            destination_justification=routing_state.get("justification"),
            status=draft_state.get("status"),
            confidence_score=confidence,
            requires_human_approval=common_fields["requires_human_approval"],
            attempts=common_fields["attempts"],
            verification=common_fields["verification"],
            judge=common_fields["judge"],
            missing_information=missing_information,
            instructions=request.instructions,
        )
        return DraftResponseSchema(
            **common_fields,
            draft_id=draft_id or "",
            destination=destination,
            justification=routing_state.get("justification", "Yönlendirme kararı alınamadı."),
        )

    @staticmethod
    def _trace_config(user_id: Optional[str] = None, company_id: Optional[str] = None) -> dict[str, Any]:
        try:
            from app.observability.tracer import build_trace_config, company_tags

            return build_trace_config(
                langfuse_user_id=user_id, langfuse_tags=company_tags(company_id)
            )
        except Exception:
            return {}
