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
    """Evrak taslağı oluşturma ve birim yönlendirme işlemlerini yürüten servis (Task 2).

    Bugün yalnızca bu doğrudan `POST /documents/draft` yolu ve
    `DraftShareService.respond`'un accept-fork'u kota kontrolüne tabidir;
    sohbet kaynaklı taslak üretimi değil -- bu aynı dürüstlüğün token-kotası
    karşılığı için `QuotaService`'in modül docstring'ine, nedeni için de
    `docs/api/root.md`/`analytics.md`'ye bakın: sohbet akışı bir turun taslak
    üretip üretmeyeceğine derlenmiş `planning_graph`'ın çok derininde karar
    verir, ve bu kod tabanının kendi katmanlama kuralı (`app.ai.*` asla
    `app.domains.*`'ı import etmez -- bkz. `app.domains.units.provider`'ın
    docstring'i) bu kuralı ihlal etmeden DB destekli bir kota kontrolünün
    kararın verildiği noktada yer alamayacağı anlamına gelir; gizlilik
    yetkisinin ABAC motorunun kendisinin dışında tutulmasıyla aynı sebep
    (bkz. `app.core.authz.engine`'in modül docstring'i).
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
        """Taslak oluşturma ve yönlendirme iş akışlarını sırayla çalıştırır.

        Args:
            request: Taslak oluşturma isteği.
            user_id: Kimliği doğrulanmış çağıranın id'si -- kalıcı taslak
                sürümüne eklenir (bkz. ``app.domains.drafts.draft_recorder``).
            company_id: Kimliği doğrulanmış çağıranın şirketi -- yönlendirme
                iş akışının seçim yapacağı birim listesini kapsar.
        """
        if self.quota_service is not None:
            await self.quota_service.check_and_increment(company_id, DRAFTS_METRIC)


        # 1. Ham evrakı getir ve metni çıkar
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

        # 2. Taslak oluşturma iş akışını çalıştır
        # WriterAgent'ı bilgilendirmek için mevzuat_references'tan bağlam oluştur
        context_lines = [
            f"- {ref.mevzuat}: {ref.aciklama}"
            for ref in request.classification.mevzuat_references
            if ref.mevzuat
        ]
        context_str = "\n".join(context_lines) if context_lines else ""

        # draft_graph'ın iç yardımcıları (_build_brief, verify_draft, ...)
        # classification'ı düz bir dict olarak ele alır; tipli
        # DraftClassificationSchema sınır doğrulamasıdır, graph'ın iç
        # temsili değildir.
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
                        "document_id": request.storage_path,
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
        # DraftModel.verification'ın ayrı bir applied_rules sütunu yok (zaten
        # bir JSON blob, migration gerekmiyor) -- kalıcı kayıt sadece yanıt
        # şemasının üst düzey alanını değil, denetlenebilir tam puan
        # dökümünü de taşısın diye burada birleştirildi.
        verification_for_storage = {
            **common_fields["verification"],
            "applied_rules": common_fields["applied_rules"],
        }

        # Bu endpoint'in kendi session/interrupt mekanizması yok (bu iş
        # /chat/resume üzerinden sohbet yolunun görevi) -- doldurulmamış
        # yer tutucular içeren bir taslak yönlendirilmek yerine olduğu gibi
        # raporlanır; çünkü belirgin şekilde eksik bir taslağı bir birime
        # yönlendirmek, hiç yönlendirmemekten daha kötüdür.
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

        # 3. Yönlendirme iş akışını çalıştır
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
        # Yönlendirme bir birimi güvenle atayamadı (boş taslak, düşük skor,
        # bir LLM hatası veya halüsinasyon bir birim adı) -- yukarıdaki
        # taslak kalite kapısının zaten kullandığı aynı bayrak, üzerine
        # yazılmak yerine OR'lanır; çünkü her iki kaynak da bu taslağın
        # herhangi bir yere gitmeden önce bir insan tarafından incelenmesi
        # için geçerli bir sebeptir.
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
            # C29: bu başarı dalı verification_for_storage'ı hesaplıyordu
            # (applied_rules, yukarıdaki missing_information dalıyla aynı
            # şekilde verification blob'una katlanmış) ama hiç kullanmıyordu
            # -- başarıyla yönlendirilen her taslak, yanıt şemasının üst
            # düzey applied_rules alanına giren denetlenebilir kural
            # dökümü olmadan verification'ını kalıcı hale getiriyordu.
            verification=verification_for_storage,
            judge=common_fields["judge"],
            missing_information=missing_information,
            instructions=request.instructions,
        )
        return DraftResponseSchema(
            **common_fields,
            draft_id=draft_id or "",
            destination=destination,
            alternative_units=routing_state.get("alternative_units") or [],
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
