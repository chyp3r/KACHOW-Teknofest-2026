import asyncio
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from app.ai.compliance.checker import check_required_fields
from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.ai.documents.anchors import build_page_map
from app.ai.guardrails.file_integrity import check_file_integrity
from app.ai.guardrails.injection import scrub_extracted_text
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.domains.quotas.service import DOCUMENTS_METRIC, QuotaService
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.validation import ValidationException
from app.core.config import settings
from app.core.constants import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_FILE_TYPES,
    MAX_FILE_SIZE_BYTES,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.core.enums.sensitivity_level import SensitivityLevel
from app.domains.documents.schema.document_schema import (
    DocumentAnalysisResponseSchema,
    ExtractionInfoSchema,
    GuardrailAssessmentSchema,
    MevzuatReferenceSchema,
    PiiFindingSchema,
)
from app.events.event import DocumentAnalyzedEvent, DocumentUploadedEvent
from app.events.event_bus import event_bus
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
)
from app.infrastructure.storage.base import BaseStorage
from app.ai.embeddings.service import EmbeddingService
from app.ai.embeddings.chunking.recursive import RecursiveChunker
from app.ai.retrieval.sparse_encoder import SparseBM25Encoder
from app.infrastructure.vectorstore.base import BaseVectorStore
from app.observability import company_metrics, guardrail_recorder
from app.shared.validator.file_validator import validate_file_extension

logger = logging.getLogger(__name__)

UPLOAD_PATH_PREFIX = "uploads"
MIN_ANALYSABLE_CHAR_COUNT = 20

#: Q&A index settings. Must stay in sync with the retrieval side in
#: planning_graph's document_qa step.
QA_COLLECTION_NAME = "document_qa"
QA_CHUNK_SIZE = 1000
QA_CHUNK_OVERLAP = 200

#: Cached embedding dimension, probed once per process.
_qa_vector_size: Optional[int] = None


class DocumentService:
    """Business logic for the first-review (ön inceleme) stage of incoming evrak."""

    def __init__(
        self,
        storage: BaseStorage,
        extractor: BaseDocumentExtractor,
        analysis_graph: Any,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[BaseVectorStore] = None,
        document_repository: Optional[DocumentRepository] = None,
        pool_repository: Optional[DocumentPoolRepository] = None,
        pool_item_repository: Optional[DocumentPoolItemRepository] = None,
        quota_service: Optional[QuotaService] = None,
    ) -> None:
        """Initialise the service with injected collaborators.

        Args:
            storage: Storage backend for the raw uploaded document.
            extractor: Text extraction chain.
            analysis_graph: Compiled document analysis workflow.
            document_repository: Ownership/listing registry (see
                `DocumentModel`). Optional so callers that only exercise
                extraction/analysis (most unit tests) don't need a database --
                when absent, a document is analysed exactly as before but
                never registered, which also means it never appears in
                `GET /documents` or passes an ownership check.
            pool_repository, pool_item_repository: The evrak havuzu (see
                `app.domains.pools`) every upload files itself into (its
                owner's personal default pool). Optional for the same
                reason `document_repository` is -- when absent, a document
                is registered exactly as before but never pool-filed.
            quota_service: Enforces `company_quotas.max_documents_per_month`
                (see `app.domains.quotas`). Optional for the same reason as
                above -- when absent, uploads are never quota-gated (every
                pre-Faz-6 caller, and most unit tests).
        """
        self.storage = storage
        self.extractor = extractor
        self.analysis_graph = analysis_graph
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.document_repository = document_repository
        self.pool_repository = pool_repository
        self.pool_item_repository = pool_item_repository
        self.quota_service = quota_service

    async def analyze_document(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: Optional[str] = None,
        owner_id: str,
        company_id: str,
    ) -> DocumentAnalysisResponseSchema:
        """Store, extract and analyse an incoming official document.

        Args:
            file_name: Original name of the uploaded file.
            content: Raw file bytes.
            content_type: Declared MIME type, when the client supplied one.
            owner_id: The authenticated caller's id -- registered as the
                document's owner.
            company_id: The authenticated caller's company -- registered as
                the document's tenant.

        Returns:
            The full first-review result.

        Raises:
            ValidationException: If the upload is rejected or yields no text.
            AIException: If the analysis workflow fails or times out.
        """
        await self._validate_upload(file_name, content, content_type)

        # Gated after the cheap upload-shape validation (rejecting a garbage
        # file never touches the quota) but before extraction/analysis --
        # the expensive half of this pipeline -- begins. See `QuotaService`'s
        # module docstring for why only "documents"/"drafts" are enforced,
        # not tokens.
        if self.quota_service is not None:
            await self.quota_service.check_and_increment(company_id, DOCUMENTS_METRIC)

        storage_path = await self._store(file_name, content)
        await self._publish(
            DocumentUploadedEvent(
                payload={
                    "file_name": file_name,
                    "storage_path": storage_path,
                    "size_bytes": len(content),
                }
            )
        )

        try:
            extracted = await self.extractor.extract(
                content, file_name=file_name, mime_type=content_type
            )
        except DocumentExtractionError as exc:
            raise ValidationException(
                message="Belgeden metin çıkarılamadı.", details={"reason": str(exc)}
            ) from exc

        # A submitted document is attacker-controlled input from the prompt's
        # perspective. Scrub per page, not the already-joined text -- a page
        # read directly via get_document_section must carry the same
        # guarantee as the joined text every other path sees. Re-joining the
        # scrubbed pages (rather than re-scrubbing the join) keeps char
        # offsets consistent with what PageMap/chunking later compute from
        # these same pages.
        scrubbed_pages: list[str] = []
        scrubbed_markers: list[str] = []
        for page_text in extracted.pages or [extracted.text]:
            cleaned, markers = scrub_extracted_text(page_text)
            scrubbed_pages.append(cleaned)
            scrubbed_markers.extend(markers)
        extracted.pages = scrubbed_pages
        extracted.text = "\n\n".join(scrubbed_pages)
        if scrubbed_markers:
            logger.warning(
                "Scrubbed possible prompt injection from %s: %s", storage_path, scrubbed_markers
            )

        if extracted.char_count < MIN_ANALYSABLE_CHAR_COUNT:
            raise ValidationException(
                message=(
                    "Belgeden anlamlı metin çıkarılamadı. Taranmış bir belge ise "
                    "daha yüksek çözünürlüklü bir kopya yükleyin."
                ),
                details={
                    "extractor": extracted.extractor,
                    "char_count": extracted.char_count,
                },
            )

        state = await self._run_analysis(extracted.text, extracted.used_ocr, owner_id, company_id)
        response = self._assemble(file_name, storage_path, extracted, state, scrubbed_markers)
        await self._register_document(file_name, storage_path, owner_id, company_id, response)
        await self._save_document_analysis_cache(
            storage_path, extracted.text, extracted.pages, response
        )

        await self._index_for_qa(
            storage_path,
            extracted.text,
            extracted.pages,
            sensitivity_level=response.guardrail.sensitivity_level,
        )
        await self._record_sensitivity_assessment(storage_path, owner_id, company_id, response)

        await self._publish(
            DocumentAnalyzedEvent(
                payload={
                    "file_name": file_name,
                    "document_type": response.document_type.value,
                    "compliance_status": response.compliance_status.value,
                    "missing_field_count": len(response.missing_fields),
                }
            )
        )
        return response

    async def _index_for_qa(
        self,
        storage_path: str,
        text: str,
        pages: Optional[list[str]] = None,
        sensitivity_level: SensitivityLevel = SensitivityLevel.UNMARKED,
    ) -> None:
        """Chunk, embed and index the document so Document Q&A can find it.

        The collection dimension is probed from a real embedding rather than
        hard-coded. It used to be pinned at 3584 (a 7B model's hidden size) while
        the configured embedding model emits 768, so every upsert was rejected,
        the failure was swallowed by this method's except clause, and the
        collection stayed permanently empty -- Document Q&A answered "belgede
        bulunamadı" for every question ever asked.

        Each chunk also gets a sparse (BM25-style) vector alongside the dense
        one and is tagged with ``storage_path`` in its payload -- the same
        identifier the document-scoped query side filters on -- so retrieval
        can run Qdrant's native hybrid (dense + sparse) search restricted to
        this one document instead of a plain dense-only lookup. It is also
        tagged with ``page`` (via ``PageMap`` + the chunker's
        ``start_index``), so a search hit can be cited by page instead of
        being an anonymous passage.

        Args:
            storage_path: Storage reference, used as the document identifier.
            text: Full extracted document text.
            pages: Per-page extracted text, in document order, used to map
                each chunk's offset in ``text`` to a page number.
            sensitivity_level: The document-level assessment from
                ``app.ai.guardrails.sensitivity.assess``, stamped onto every
                chunk as both the string level (display/logging) and its
                numeric ``rank`` (what a Qdrant range filter can actually
                compare against -- wired up in the RBAC phase). Document
                granularity for now; re-assessing per chunk is a later
                refinement, not required to make retrieval-time filtering
                possible.
        """
        if not self.embedding_service or not self.vector_store:
            return

        try:
            chunker = RecursiveChunker(
                chunk_size=QA_CHUNK_SIZE, chunk_overlap=QA_CHUNK_OVERLAP
            )
            chunks = await self.embedding_service.process_text(text, chunker=chunker)
            if not chunks:
                logger.warning("Document %s produced no chunks to index.", storage_path)
                return

            page_map = build_page_map(pages or [text])

            # Unfit on purpose: its sparse indices are CRC32 hashes of tokens,
            # not corpus-fitted ids, so no shared vocabulary is needed across
            # documents. Document-side encoding only uses avg_doc_len (falls
            # back sanely to each chunk's own length when unset); query-side
            # IDF weights default to a uniform 1.0. Fitting per single-document
            # upload would be pointless anyway -- BM25 IDF over a corpus of one
            # document is a constant.
            encoder = SparseBM25Encoder()
            for chunk in chunks:
                chunk.metadata["storage_path"] = storage_path
                chunk.metadata["sensitivity_level"] = sensitivity_level.value
                chunk.metadata["sensitivity_rank"] = sensitivity_level.rank
                start_index = chunk.metadata.get("start_index")
                if start_index is not None:
                    chunk.metadata["page"] = page_map.page_for_offset(start_index)
                indices, values = encoder.encode_document(chunk.text)
                chunk.sparse_vector = {"indices": indices, "values": values}

            vector_size = await self._probe_embedding_dimension()
            if vector_size is None:
                return

            created = await self.vector_store.create_collection(
                QA_COLLECTION_NAME, vector_size=vector_size, distance="Cosine"
            )
            if not created:
                # create_collection's return value used to go unchecked: when an
                # existing collection had a stale dimension (left over from a
                # previous embedding model), _validate_existing correctly
                # rejected it and logged an error, but upsert_documents ran
                # anyway and failed on every point with a Qdrant 400. Rebuilding
                # is safe here -- a collection that fails validation has never
                # accepted a write under the current embedding model, so there
                # is no current data to lose.
                logger.warning(
                    "'%s' is incompatible with the current embedding dimension "
                    "(%d); recreating it.",
                    QA_COLLECTION_NAME,
                    vector_size,
                )
                await self.vector_store.delete_collection(QA_COLLECTION_NAME)
                created = await self.vector_store.create_collection(
                    QA_COLLECTION_NAME, vector_size=vector_size, distance="Cosine"
                )
                if not created:
                    logger.error(
                        "Could not (re)create '%s'; skipping Q&A index for %s.",
                        QA_COLLECTION_NAME,
                        storage_path,
                    )
                    return

            stored = await self.vector_store.upsert_documents(QA_COLLECTION_NAME, chunks)
            if not stored:
                logger.error(
                    "Upsert failed for document %s into '%s'.",
                    storage_path,
                    QA_COLLECTION_NAME,
                )
                return

            logger.info(
                "Indexed %d chunk(s) for Q&A on document %s (vector_size=%d).",
                len(chunks),
                storage_path,
                vector_size,
            )
        except Exception:
            logger.exception(
                "Failed to embed and index document %s for Q&A", storage_path
            )

    async def _probe_embedding_dimension(self) -> Optional[int]:
        """Detect the embedding dimension by embedding a throwaway string.

        Returns:
            The dimension, or None when the embedding service is unreachable.
        """
        global _qa_vector_size
        if _qa_vector_size is not None:
            return _qa_vector_size

        try:
            probe = await self.embedding_service.embeddings_client.embed_query("boyut")
        except Exception:
            logger.exception("Could not probe embedding dimension; skipping Q&A index.")
            return None

        _qa_vector_size = len(probe)
        logger.info("Detected Q&A embedding dimension: %d", _qa_vector_size)
        return _qa_vector_size

    async def _validate_upload(
        self, file_name: str, content: bytes, content_type: Optional[str]
    ) -> None:
        """Reject uploads that are empty, oversized, of an unsupported type,
        or whose bytes don't actually match what they claim to be.

        Args:
            file_name: Original file name.
            content: Raw file bytes.
            content_type: Declared MIME type.

        Raises:
            ValidationException: If any check fails.
        """
        if not content:
            raise ValidationException(message="Yüklenen dosya boş.")

        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValidationException(
                message="Dosya boyutu izin verilen sınırı aşıyor.",
                details={
                    "max_size_bytes": MAX_FILE_SIZE_BYTES,
                    "size_bytes": len(content),
                },
            )

        extension_ok = validate_file_extension(file_name, ALLOWED_DOCUMENT_EXTENSIONS)
        mime_ok = content_type in ALLOWED_FILE_TYPES if content_type else False
        if not extension_ok and not mime_ok:
            raise ValidationException(
                message="Desteklenmeyen dosya türü.",
                details={
                    "file_name": file_name,
                    "content_type": content_type,
                    "allowed_types": ALLOWED_FILE_TYPES,
                    "allowed_extensions": ALLOWED_DOCUMENT_EXTENSIONS,
                },
            )

        # Extension and Content-Type are both strings the uploader controls;
        # neither says anything about the actual bytes. This is the
        # deterministic hard-block tier: a mismatched signature or an
        # archive that would decompress into something absurd is rejected
        # outright, before storage or extraction ever touch the content.
        integrity = check_file_integrity(content, file_name=file_name, content_type=content_type)
        if not integrity.ok:
            await guardrail_recorder.record_event(
                stage="input",
                kind="magic_byte",
                decision="blocked",
                reasons=[integrity.reason],
                company_id=company_id,
                requester_user_id=owner_id,
            )
            raise ValidationException(
                message="Dosya içeriği doğrulanamadı.",
                details={"reason": integrity.reason, "file_name": file_name},
            )

    async def _store(self, file_name: str, content: bytes) -> str:
        """Persist the raw upload under a collision-free key.

        Args:
            file_name: Original file name, used only for its extension.
            content: Raw file bytes.

        Returns:
            The storage reference returned by the backend.
        """
        extension = os.path.splitext(file_name)[1].lower()
        key = f"{UPLOAD_PATH_PREFIX}/{uuid4().hex}{extension}"
        return await self.storage.put_file(key, content)

    async def _run_analysis(
        self,
        text: str,
        used_ocr: bool,
        owner_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Invoke the analysis workflow under a timeout.

        Args:
            text: Extracted document text.
            used_ocr: Whether the text came from OCR.
            owner_id, company_id: Attached as Langfuse trace metadata (see
                ``_trace_config``) when known.

        Returns:
            The final workflow state.

        Raises:
            AIException: If the workflow fails or exceeds the timeout.
        """
        try:
            return await asyncio.wait_for(
                self.analysis_graph.ainvoke(
                    {"input_text": text, "is_ocr_text": used_ocr},
                    config=self._trace_config(owner_id, company_id),
                ),
                timeout=settings.AI_WORKFLOW_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Evrak analizi zaman aşımına uğradı.",
                details={"timeout_seconds": settings.AI_WORKFLOW_TIMEOUT_SECONDS},
            ) from exc
        except Exception as exc:
            logger.exception("Document analysis workflow failed")
            raise AIException(
                message="Evrak analizi sırasında bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

    @staticmethod
    def _trace_config(owner_id: Optional[str] = None, company_id: Optional[str] = None) -> dict[str, Any]:
        """Build the LangGraph config, attaching Langfuse tracing when available.

        Imported lazily and defensively: the Langfuse LangChain integration needs
        the monolithic `langchain` package, so an unavailable tracer must degrade
        to "no tracing" rather than failing every upload.

        Args:
            owner_id, company_id: Attached as Langfuse trace metadata (see
                ``app.observability.tracer.build_trace_config``) when known.

        Returns:
            A LangGraph config dict, empty when tracing is unavailable.
        """
        try:
            from app.observability.tracer import build_trace_config, company_tags

            return build_trace_config(
                langfuse_user_id=owner_id, langfuse_tags=company_tags(company_id)
            )
        except Exception:
            logger.debug("Langfuse tracing unavailable; continuing without it.")
            return {}

    @staticmethod
    def _assemble(
        file_name: str,
        storage_path: str,
        extracted: Any,
        state: dict[str, Any],
        scrubbed_markers: Optional[list[str]] = None,
    ) -> DocumentAnalysisResponseSchema:
        """Build the API response from the final workflow state.

        Args:
            file_name: Original file name.
            storage_path: Storage reference of the raw upload.
            extracted: The `ExtractedDocument` produced by the extractor.
            state: Final workflow state.
            scrubbed_markers: Markers describing content removed by the
                prompt-injection guardrail, if any.

        Returns:
            The populated response schema.
        """
        try:
            document_type = DocumentType(
                state.get("document_type", DocumentType.OTHER.value)
            )
        except ValueError:
            document_type = DocumentType.OTHER

        try:
            compliance_status = ComplianceStatus(
                state.get("compliance_status", ComplianceStatus.INCOMPLETE.value)
            )
        except ValueError:
            compliance_status = ComplianceStatus.INCOMPLETE

        raw_assessment = state.get("sensitivity_assessment") or {}
        try:
            sensitivity_level = SensitivityLevel(
                raw_assessment.get("level", SensitivityLevel.UNMARKED.value)
            )
        except ValueError:
            sensitivity_level = SensitivityLevel.UNMARKED
        guardrail = GuardrailAssessmentSchema(
            sensitivity_level=sensitivity_level,
            pii_findings=[
                PiiFindingSchema(kind=item.get("kind", ""), preview=item.get("preview", ""))
                for item in raw_assessment.get("pii_findings") or []
            ],
            requires_human_review=bool(raw_assessment.get("requires_review", False)),
            reasons=list(raw_assessment.get("reasons") or []),
        )

        return DocumentAnalysisResponseSchema(
            file_name=file_name,
            storage_path=storage_path,
            analysis_id=storage_path,
            extraction=ExtractionInfoSchema(
                extractor=extracted.extractor,
                page_count=extracted.page_count,
                char_count=extracted.char_count,
                used_ocr=extracted.used_ocr,
                scrubbed_markers=scrubbed_markers or [],
            ),
            document_type=document_type,
            document_type_label=state.get("document_type_label", ""),
            summary=state.get("summary", ""),
            fields=EvrakField(**(state.get("fields") or {})),
            missing_fields=[
                MissingField(**item) for item in state.get("missing_fields") or []
            ],
            compliance_status=compliance_status,
            mevzuat_references=[
                MevzuatReferenceSchema(**item)
                for item in state.get("mevzuat_suggestions") or []
            ],
            guardrail=guardrail,
        )

    @staticmethod
    async def _publish(event: Any) -> None:
        """Publish a domain event without letting listener failures break intake.

        Args:
            event: The event to publish.
        """
        try:
            await event_bus.publish(event)
        except Exception:
            logger.exception(
                "Failed to publish event %s", getattr(event, "event_type", "?")
            )

    async def _register_document(
        self,
        file_name: str,
        storage_path: str,
        owner_id: str,
        company_id: str,
        response: DocumentAnalysisResponseSchema,
    ) -> None:
        """Register the document's ownership + listing metadata in Postgres.

        Replaces the old uploads_metadata.json file (which had no concept of
        an owner at all -- see DocumentModel's docstring). A no-op when this
        service was built without a repository (most unit tests), same as
        before when the JSON write was best-effort and non-fatal.
        """
        if self.document_repository is None:
            return
        try:
            await self.document_repository.create(
                DocumentModel(
                    id=storage_path,
                    owner_id=owner_id,
                    company_id=company_id,
                    file_name=file_name,
                    document_type=response.document_type.value,
                    document_type_label=response.document_type_label,
                    compliance_status=response.compliance_status.value,
                    summary=response.summary,
                    sensitivity_level=response.guardrail.sensitivity_level.value,
                    pii_flagged=bool(response.guardrail.pii_findings),
                )
            )
            await self._file_into_default_pool(storage_path, owner_id, company_id)
            slug = company_metrics.cached_slug(company_id)
            if slug is not None:
                company_metrics.note_document_registered(slug)
        except Exception:
            logger.exception("Failed to register document %s", storage_path)

    async def _file_into_default_pool(self, storage_path: str, owner_id: str, company_id: str) -> None:
        """File a freshly-registered document into its uploader's personal pool.

        Same "personal pool" concept `app.domains.pools.service.PoolService.
        get_or_create_personal_pool` lazily creates on first read -- this is
        the other lazy-creation path, on first *write* (an upload), so a
        pool exists and already has content the first time its owner opens
        `GET /pools/me`. A no-op, not an error, when this service was built
        without pool repositories (most unit tests) -- same optionality as
        `document_repository` itself.
        """
        if self.pool_repository is None or self.pool_item_repository is None:
            return
        pool = await self.pool_repository.get_or_create_default(
            "user", owner_id, company_id, name="Kişisel Havuz"
        )
        await self.pool_item_repository.create(
            DocumentPoolItemModel(
                id=uuid4().hex,
                company_id=company_id,
                pool_id=pool.id,
                document_id=storage_path,
                added_by=owner_id,
                source="upload",
            )
        )

    @staticmethod
    async def _record_sensitivity_assessment(
        storage_path: str,
        owner_id: str,
        company_id: str,
        response: DocumentAnalysisResponseSchema,
    ) -> None:
        """Record the input-side guardrail audit event for one upload.

        A separate call from the ``magic_byte`` block recorded in
        ``_validate_upload`` -- that one fires on outright rejection before
        a ``storage_path`` even exists; this one fires on every successfully
        analysed document, whatever its assessment turned out to be, so the
        audit trail has one row per upload rather than only the rejections.
        """
        guardrail = response.guardrail
        if guardrail.requires_human_review:
            decision = "needs_review"
        elif guardrail.pii_findings:
            decision = "flagged"
        else:
            decision = "passed"

        await guardrail_recorder.record_event(
            stage="input",
            kind="sensitivity",
            decision=decision,
            document_id=storage_path,
            company_id=company_id,
            requester_user_id=owner_id,
            reasons=guardrail.reasons,
            related_document_ids=[storage_path],
        )

    async def _save_document_analysis_cache(
        self,
        storage_path: str,
        extracted_text: str,
        pages: list[str],
        response: DocumentAnalysisResponseSchema,
    ) -> None:
        """Save full document analysis, extracted text and per-page text to a
        local cache JSON file.

        ``pages`` backs the ``get_document_outline``/``get_document_section``
        tools (see ``app.ai.tools.document_tools``) -- without it, a page
        request would have nothing to index into once the analysis workflow
        has already returned.
        """
        import json
        from app.core.config import settings

        cache_file = os.path.join(settings.LOCAL_STORAGE_DIR, f"{storage_path}_analysis.json")

        def _write():
            cache_data = {
                "extracted_text": extracted_text,
                "pages": pages,
                "analysis": response.model_dump(mode="json")
            }
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

        try:
            await asyncio.to_thread(_write)
        except Exception as e:
            logger.error(f"Failed to save document analysis cache: {e}")

    async def get_cached_analysis(
        self, storage_path: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Read a previously computed analysis back from the local cache file.

        Backs ``GET /documents/{storage_path}``. Before this, the frontend
        only had the 7-field projection in ``uploads_metadata.json`` (used by
        ``GET /documents``), so re-selecting a document from the library lost
        ``missing_fields`` and ``mevzuat_references`` entirely.

        Args:
            storage_path: The document's storage key.

        Returns:
            The cached analysis response, or None if no cache exists for it
            or the cache fails to parse.
        """
        import json
        from app.core.config import settings

        cache_file = os.path.join(settings.LOCAL_STORAGE_DIR, f"{storage_path}_analysis.json")

        def _read():
            if not os.path.exists(cache_file):
                return None
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            cache_data = await asyncio.to_thread(_read)
        except Exception:
            logger.exception("Failed to read cached analysis for %s", storage_path)
            return None

        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            return DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

    async def update_document_fields(
        self, storage_path: str, fields: EvrakField, company_id: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Apply a user-corrected field set and re-run compliance.

        Backs the "edit extracted fields" UI on the document analysis panel
        -- until this, an undetected/wrong field (``EvrakField``'s empty
        slots) was permanently read-only. Re-checks the same deterministic
        rule table the original analysis used
        (``app.ai.compliance.checker.check_required_fields``, no model
        call), so ``missing_fields``/``compliance_status`` reflect the
        correction immediately instead of staying stuck at whatever the
        extraction originally found.

        Rewrites the same local cache file ``get_cached_analysis`` reads
        back, preserving ``extracted_text``/``pages`` (the document Q&A
        tools index into them, see ``_save_document_analysis_cache``) --
        only ``fields``, ``missing_fields`` and ``compliance_status`` change.

        Args:
            storage_path: The document's storage key.
            fields: The full corrected field set (replaces, not patches).

        Returns:
            The updated analysis, or None if no cache exists for
            ``storage_path`` (or it fails to parse).
        """
        import json
        from app.core.config import settings

        cache_file = os.path.join(settings.LOCAL_STORAGE_DIR, f"{storage_path}_analysis.json")

        def _read():
            if not os.path.exists(cache_file):
                return None
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        try:
            cache_data = await asyncio.to_thread(_read)
        except Exception:
            logger.exception("Failed to read cached analysis for %s", storage_path)
            return None

        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        analysis.fields = fields
        report = check_required_fields(analysis.document_type, fields)
        analysis.missing_fields = report.missing_fields
        analysis.compliance_status = report.status

        await self._save_document_analysis_cache(
            storage_path,
            cache_data.get("extracted_text", ""),
            cache_data.get("pages", []),
            analysis,
        )

        if self.document_repository is not None:
            document = await self.document_repository.get_by_id(storage_path, company_id)
            if document is not None:
                document.compliance_status = analysis.compliance_status.value

        return analysis

    async def delete_document(self, storage_path: str, company_id: str) -> None:
        """Permanently remove a document: registry row, raw file, analysis
        cache, and any indexed Q&A chunks.

        Best-effort past the registry row -- once that row is gone the
        document no longer appears in `GET /documents` regardless of
        whether the remaining cleanup steps below succeed, so a
        storage/cache/vector-store hiccup is logged and swallowed here
        rather than surfaced as a failed delete the caller would retry.

        Args:
            storage_path: The document's storage key.
            company_id: The caller's company -- deletion is scoped to it,
                same as every other document read/write.
        """
        if self.document_repository is not None:
            await self.document_repository.delete(storage_path, company_id)

        try:
            await self.storage.delete_file(storage_path)
        except Exception:
            logger.exception("Failed to delete stored file for %s", storage_path)

        cache_file = os.path.join(settings.LOCAL_STORAGE_DIR, f"{storage_path}_analysis.json")

        def _remove_cache():
            if os.path.exists(cache_file):
                os.remove(cache_file)

        try:
            await asyncio.to_thread(_remove_cache)
        except Exception:
            logger.exception("Failed to delete cached analysis for %s", storage_path)

        if self.vector_store is not None:
            try:
                await self.vector_store.delete_by_filter(
                    QA_COLLECTION_NAME, {"storage_path": storage_path}
                )
            except Exception:
                logger.exception("Failed to delete indexed chunks for %s", storage_path)
