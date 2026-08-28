import asyncio
import json
import logging
import os
from typing import Any, Optional
from uuid import uuid4

from app.ai.agents.summarizer import SummarizerAgent
from app.ai.compliance.checker import check_required_fields
from app.ai.compliance.evrak_field import EvrakField, MissingField
from app.ai.compliance.field_parser import merge_parsed_over_model, parse_labelled_fields
from app.ai.documents.anchors import build_page_map
from app.ai.guardrails.file_integrity import check_file_integrity
from app.ai.guardrails.injection import scrub_extracted_text
from app.ai.guardrails.sensitivity import assess as assess_sensitivity
from app.ai.policy import get_policy
from app.ai.summarization import build_detailed_summary
from app.domains.documents.cache_keys import analysis_cache_key
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.repository import DocumentRepository
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.repository import DocumentPoolItemRepository, DocumentPoolRepository
from app.domains.documents.knowledge_graph import (
    DocumentGraphInput,
    KnowledgeGraph,
    MevzuatReferenceInput,
    MissingFieldInput,
    build_knowledge_graph,
)
from app.domains.quotas.service import DOCUMENTS_METRIC, QuotaService
from app.domains.users.model.user_model import UserModel
from app.api.exceptions.ai_error import AIException
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.core.config import settings
from app.core.constants import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_FILE_TYPES,
    MAX_FILE_SIZE_BYTES,
    MIN_EXTRACTED_CHAR_COUNT,
    MIN_TEXT_QUALITY_RATIO,
)
from app.core.enums.compliance_status import ComplianceStatus
from app.core.enums.document_type import DocumentType
from app.core.enums.sensitivity_level import SensitivityLevel
from app.domains.documents.schema.document_schema import (
    DetectedMarkSchema,
    DocumentAnalysisResponseSchema,
    DocumentTextSchema,
    ExtractionInfoSchema,
    GuardrailAssessmentSchema,
    MevzuatReferenceSchema,
    PiiFindingSchema,
    SignatureAssessmentSchema,
)
from app.events.event import DocumentAnalyzedEvent, DocumentUploadedEvent
from app.events.event_bus import event_bus
from app.infrastructure.extractors.base import (
    BaseDocumentExtractor,
    DocumentExtractionError,
    ExtractedDocument,
)
from app.infrastructure.cache.redis import RedisCache
from app.infrastructure.extractors.marks import DetectedMark
from app.infrastructure.extractors.vision import EvrenVisionExtractor, VisionExtractorBase
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

#: Korpus-grafiği ayarları. Sınır, istek başına yapılan disk okumasını
#: sınırlar (ayakta kalan her belgenin analiz önbelleği tamamen okunur) --
#: 200 belge, tek bir istek/yanıt döngüsüne rahatça sığan yaklaşık 2MB
#: JSON'a denk gelir. Bunun ötesinde çözüm daha büyük bir sınır değil, önceden
#: hesaplanmış bir özet olmalıdır (bkz. oturum planının risk bölümü).
MAX_GRAPH_DOCUMENTS = 200
GRAPH_CACHE_TTL_SECONDS = 60


def _graph_to_json_dict(graph: KnowledgeGraph) -> dict[str, Any]:
    """`KnowledgeGraph`'ı, kesinlikle JSON-yerel türler (tuple değil, liste)
    içeren bir sözlüğe düzleştirir.

    `dataclasses.asdict`, iç içe geçmiş dataclass'lara özyinelemeli olarak
    iner ama tuple alanları tuple olarak bırakır -- yani önbelleğe alınmamış
    bir çağrı `nodes: (...)` döndürürken, önbelleğe alınmış bir çağrı
    (`json.dumps`/`json.loads` gidiş-dönüşünden sonra) `nodes: [...]`
    döndürür; aynı alan sadece önbellek durumuna bağlı olarak iki farklı
    Python türü taşır. Her çağrıyı burada tek bir JSON gidiş-dönüşünden
    geçirmek, şeklin her iki durumda da aynı olmasını sağlar.
    """
    import dataclasses
    import json

    return json.loads(json.dumps(dataclasses.asdict(graph), default=str))

#: Soru-cevap indeksi ayarları. planning_graph'ın document_qa adımındaki
#: erişim (retrieval) tarafıyla senkron kalmalıdır. Chunk boyutu/örtüşmesi,
#: yerel sabit değerler yerine ChunkingPolicy.qa_* içinden alınır -- bu
#: sınıfın neden kendi politika bölümüne sahip olduğu ve neden (henüz) bir
#: strateji anahtarı taşımadığı için o sınıfın docstring'ine bakın.
QA_COLLECTION_NAME = "document_qa"
QA_CHUNK_SIZE = get_policy().chunking.qa_chunk_size
QA_CHUNK_OVERLAP = get_policy().chunking.qa_chunk_overlap

#: İşlem başına bir kez ölçülen, önbelleğe alınmış embedding boyutu.
_qa_vector_size: Optional[int] = None


#: Eski private ismiyle yeniden dışa aktarılır -- bu modülün kendi çağrı
#: noktaları ve mevcut testler bunu `_analysis_cache_key` olarak yazıyor.
#: Tanımın kendisi `cache_keys.py`'a taşındı, böylece
#: `app.domains.documents.provider` (planning graph tarafından enjekte
#: edilen bir callable üzerinden okunur, asla doğrudan import ile değil --
#: bkz. o modülün kendi docstring'i) de bunu paylaşabilir.
_analysis_cache_key = analysis_cache_key


class DocumentService:
    """Gelen evrakın ön inceleme aşaması için iş mantığı."""

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
        summarizer_agent: Optional[SummarizerAgent] = None,
        cache: Optional[RedisCache] = None,
        vision_extractor: Optional[VisionExtractorBase] = None,
    ) -> None:
        """Servisi enjekte edilen bağımlılıklarla başlatır.

        Args:
            storage: Yüklenen ham belge için depolama backend'i.
            extractor: Metin çıkarma zinciri.
            analysis_graph: Derlenmiş belge analiz iş akışı.
            document_repository: Sahiplik/listeleme kaydı (bkz.
                `DocumentModel`). Yalnızca çıkarma/analiz işlemlerini
                kullanan çağıranların (çoğu birim testi) veritabanına
                ihtiyaç duymaması için opsiyoneldir -- bulunmadığında belge
                eskisi gibi analiz edilir ama asla kaydedilmez; bu da onun
                `GET /documents`'ta görünmeyeceği ve sahiplik kontrolünden
                geçmeyeceği anlamına gelir.
            pool_repository, pool_item_repository: Her yüklemenin kendini
                dosyaladığı evrak havuzu (bkz. `app.domains.pools`, sahibin
                kişisel varsayılan havuzu). `document_repository` ile aynı
                sebepten opsiyoneldir -- bulunmadığında belge eskisi gibi
                kaydedilir ama havuza dosyalanmaz.
            quota_service: `company_quotas.max_documents_per_month`'ı
                uygular (bkz. `app.domains.quotas`). Yukarıdakiyle aynı
                sebepten opsiyoneldir -- bulunmadığında yüklemeler asla
                kota kontrolünden geçmez (tüm Faz-6 öncesi çağıranlar ve
                çoğu birim testi için geçerlidir).
            summarizer_agent: İstek üzerine detaylı özeti oluşturur (bkz.
                `generate_detailed_summary`). `analysis_graph`'ın aksine bu,
                bir LangGraph iş akışının parçası değildir -- `analyze_document`
                buna hiç dokunmaz, yalnızca `generate_detailed_summary` kullanır.
                Bu servisin geri kalanını test eden testlerin bir LLM
                istemcisine ihtiyaç duymaması için opsiyoneldir;
                `generate_detailed_summary`'nin kendisi buna ihtiyaç duyar
                (bkz. o metodun kendi docstring'i).
            cache: `build_corpus_graph`'ın 60 saniyelik önbelleğini
                destekler, `AnalyticsService._cached`'ın kendi Redis
                geleneğini yansıtır. Önbellek bağlanmadığında korpus
                grafiğinin yine de (her çağrıda yeniden hesaplanarak)
                çalışması için opsiyoneldir.
            vision_extractor: `extractor`'ı (fallback zincirini) tamamen
                atlayarak doğrudan tam sayfa OCR geçişi çalıştırır -- bkz.
                `reextract_document_text`; zincirin kendi otomatik yükseltme
                kuralı (bkz. `FallbackDocumentExtractor._has_enough_header_fields`)
                tetiklenmediğinde kullanıcının manuel geçersiz kılma
                seçeneğidir. `summarizer_agent` ile aynı sebepten
                opsiyoneldir; yalnızca `reextract_document_text` buna
                ihtiyaç duyar.
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
        self.summarizer_agent = summarizer_agent
        self.cache = cache
        self.vision_extractor = vision_extractor

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
            extracted = await asyncio.wait_for(
                self.extractor.extract(
                    content, file_name=file_name, mime_type=content_type
                ),
                timeout=settings.EXTRACTION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise ValidationException(
                message="Belge metni çıkarma işlemi zaman aşımına uğradı.",
                details={"timeout_seconds": settings.EXTRACTION_TIMEOUT_SECONDS},
            ) from exc
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

        state = await self._run_analysis(
            extracted.text, extracted.used_ocr, extracted.detected_marks, owner_id, company_id
        )
        response = self._assemble(file_name, storage_path, extracted, state, scrubbed_markers)
        await self._register_document(file_name, storage_path, owner_id, company_id, response)
        await self._save_document_analysis_cache(
            storage_path, extracted.text, extracted.pages, response
        )

        await self._index_for_qa(
            storage_path,
            extracted.text,
            extracted.pages,
            sensitivity_level=response.guardrail.effective_sensitivity_level,
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

        Idempotent by construction: every call first deletes any chunks
        already indexed under ``storage_path`` before upserting the new
        ones. ``upsert_documents`` mints a random UUID per point, so without
        this a second call for the same document (a re-analysis, or simply
        calling this twice) would duplicate every chunk rather than replace
        them -- and ``reciprocal_rank_fusion`` dedups on exact
        ``page_content``, so duplicate points silently skew RRF ranking
        toward whichever document happened to get indexed more than once.
        Callers used to have to remember to delete first themselves; one
        caller (the primary upload path in ``analyze_document``) didn't, so
        the guarantee now lives here instead of at each call site.

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
            await self.vector_store.delete_by_filter(
                QA_COLLECTION_NAME, {"storage_path": storage_path}
            )

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
        detected_marks: Optional[list[Any]] = None,
        owner_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Invoke the analysis workflow under a timeout.

        Args:
            text: Extracted document text.
            used_ocr: Whether the text came from OCR.
            detected_marks: Signature/stamp/handwriting regions already found
                during extraction (``ExtractedDocument.detected_marks``).
                ``None`` (not an empty list) when detection never ran at all
                for this document -- ``check_compliance_node`` treats the two
                differently (unknown vs. genuinely no marks found); see its
                own comment and ``check_required_fields``'s docstring.
            owner_id, company_id: Attached as Langfuse trace metadata (see
                ``_trace_config``) when known.

        Returns:
            The final workflow state.

        Raises:
            AIException: If the workflow fails or exceeds the timeout.
        """
        initial_state: dict[str, Any] = {"input_text": text, "is_ocr_text": used_ocr}
        if detected_marks is not None:
            initial_state["detected_marks"] = [
                mark.model_dump() if hasattr(mark, "model_dump") else mark
                for mark in detected_marks
            ]
        try:
            return await asyncio.wait_for(
                self.analysis_graph.ainvoke(
                    initial_state,
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
        try:
            effective_sensitivity_level = SensitivityLevel(
                raw_assessment.get("effective_level", sensitivity_level.value)
            )
        except ValueError:
            effective_sensitivity_level = sensitivity_level
        guardrail = GuardrailAssessmentSchema(
            sensitivity_level=sensitivity_level,
            effective_sensitivity_level=effective_sensitivity_level,
            sensitivity_is_defaulted=bool(raw_assessment.get("is_defaulted", False)),
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
            # detailed_summary is never set here -- a freshly-assembled
            # response comes straight from analyze_document, before anyone
            # has asked for the detailed summary at all. It is added later,
            # in place, by generate_detailed_summary's cache mutation (see
            # that method's own docstring for why it runs on-demand rather
            # than as a graph branch here).
            fields=EvrakField(**(state.get("fields") or {})),
            missing_fields=[
                MissingField(**item) for item in state.get("missing_fields") or []
            ],
            compliance_status=compliance_status,
            signature=DocumentService._build_signature_assessment(extracted.detected_marks),
            mevzuat_references=[
                MevzuatReferenceSchema(**item)
                for item in state.get("mevzuat_suggestions") or []
            ],
            guardrail=guardrail,
        )

    @staticmethod
    def _build_signature_assessment(
        marks: Optional[list[DetectedMark]],
    ) -> SignatureAssessmentSchema:
        """Build the signature/stamp assessment from a raw `detect_marks`
        result -- shared by `_assemble` and `generate_detailed_analysis`.

        `marks is None` means detection never ran at all (see
        `ExtractedDocument.detected_marks`'s own docstring) -- `is_signed`/
        `has_stamp` must stay `None` (unknown), not `False` (checked, found
        nothing), same tri-state `check_compliance_node` already applies to
        `state["detected_marks"]`.

        Args:
            marks: `ExtractedDocument.detected_marks` -- `None` if detection
                never ran, otherwise the (possibly empty) list it found.

        Returns:
            The schema, ready to attach to a `DocumentAnalysisResponseSchema`.
        """
        return SignatureAssessmentSchema(
            is_signed=None if marks is None else any(mark.kind == "signature" for mark in marks),
            has_stamp=None if marks is None else any(mark.kind == "stamp" for mark in marks),
            marks=[
                DetectedMarkSchema(
                    kind=mark.kind, page=mark.page, bbox=mark.bbox, confidence=mark.confidence
                )
                for mark in (marks or [])
            ],
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
                    sensitivity_level=response.guardrail.effective_sensitivity_level.value,
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
        """Save full document analysis, extracted text and per-page text to
        the configured storage backend's analysis cache key (see
        ``_analysis_cache_key`` -- ``self.storage``, the same backend the
        document's own bytes live in, not necessarily local disk).

        ``pages`` backs the ``get_document_outline``/``get_document_section``
        tools (see ``app.ai.tools.document_tools``) -- without it, a page
        request would have nothing to index into once the analysis workflow
        has already returned.
        """
        cache_data = {
            "extracted_text": extracted_text,
            "pages": pages,
            "analysis": response.model_dump(mode="json"),
        }
        try:
            await self.storage.put_file(
                _analysis_cache_key(storage_path),
                json.dumps(cache_data, ensure_ascii=False, indent=2).encode("utf-8"),
            )
        except Exception as e:
            logger.error(f"Failed to save document analysis cache: {e}")

    async def _read_analysis_cache(self, storage_path: str) -> Optional[dict]:
        """Read and JSON-parse the analysis cache from storage, if it exists.

        Shared by every read-then-mutate method below (``get_cached_analysis``,
        ``update_document_fields``, ``generate_detailed_summary``) -- each owns
        a different slice of what happens after the read (a different field
        gets mutated, a different re-save follows), but "does the cache key
        exist, does it parse as JSON" was previously copy-pasted three times.

        Args:
            storage_path: The document's storage key.

        Returns:
            The parsed cache dict (with ``extracted_text``/``pages``/``analysis``
            keys -- see ``_save_document_analysis_cache``), or None if no
            cache exists for ``storage_path`` or reading/parsing it fails for
            any reason.
        """
        try:
            content = await self.storage.get_file(_analysis_cache_key(storage_path))
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception("Failed to read cached analysis for %s", storage_path)
            return None

        try:
            return json.loads(content)
        except Exception:
            logger.exception("Failed to read cached analysis for %s", storage_path)
            return None

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
        cache_data = await self._read_analysis_cache(storage_path)

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
        cache_data = await self._read_analysis_cache(storage_path)

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

    def _analysis_to_missing_field_inputs(
        self, analysis: DocumentAnalysisResponseSchema
    ) -> tuple[MissingFieldInput, ...]:
        return tuple(
            MissingFieldInput(
                key=item.key, label=item.label, severity=item.severity,
                mevzuat=item.mevzuat, reason=item.reason,
            )
            for item in analysis.missing_fields
        )

    def _analysis_to_mevzuat_reference_inputs(
        self, analysis: DocumentAnalysisResponseSchema
    ) -> tuple[MevzuatReferenceInput, ...]:
        return tuple(
            MevzuatReferenceInput(mevzuat=item.mevzuat, aciklama=item.aciklama)
            for item in analysis.mevzuat_references
        )

    @staticmethod
    def _analysis_to_entity_source_kwargs(analysis: DocumentAnalysisResponseSchema) -> dict[str, Any]:
        """Everything `DocumentGraphInput` needs beyond missing_fields/
        mevzuat_references: the raw fields Entity/Konu resolution and the
        node inspector's attribute payload are built from. One helper
        shared by `build_corpus_graph` and `build_document_graph` so the
        two never drift -- each builds its own `DocumentGraphInput` from a
        different repository path, but both read the same
        `DocumentAnalysisResponseSchema.fields` shape."""
        fields = analysis.fields
        return {
            "sayi": fields.sayi,
            "tarih": fields.tarih,
            "konu": fields.konu,
            "muhatap": fields.muhatap,
            "gonderen_kurum": fields.gonderen_kurum,
            "ivedilik": fields.ivedilik,
            "summary": analysis.summary,
            "entities": tuple(fields.entities),
        }

    async def build_corpus_graph(
        self,
        company_id: str,
        owner_id: Optional[str],
        clearance: SensitivityLevel,
    ) -> dict[str, Any]:
        """Build the compliance knowledge graph over every document a caller
        may see, deriving it on read from Postgres + the analysis cache --
        no separate graph store.

        Every candidate document<->document edge was measured against the
        real corpus before this graph was designed (see the session plan);
        the only edge type that survived is Document -> Madde, so the
        Document<->Document case this returns is always disconnected nodes
        joined only through shared maddeler -- expected, not a bug.

        Args:
            company_id: The caller's tenant. Applied to every repository
                call; never bypassed.
            owner_id: `None` for a company-wide view (ADMIN/MANAGER/ROOT,
                see `bypasses_ownership`), otherwise scoped to that user's
                own documents -- the same semantics `list_for_owner` and
                `GET /documents` already use.
            clearance: The caller's resolved confidentiality ceiling (see
                `app.core.permissions.role_checker.clearance_for`). A
                document whose `sensitivity_level` exceeds this is excluded
                entirely -- its existence is not revealed, only its count
                (`hidden_document_count`) is.

        Returns:
            A JSON-serialisable dict: `nodes`, `edges`, `insights` (the
            graph itself, flattened from `KnowledgeGraph`/`GraphInsights`
            via `dataclasses.asdict`), plus `truncated`,
            `total_document_count` and `hidden_document_count`. Returning a
            plain dict rather than the `KnowledgeGraph` dataclass lets a
            cache hit skip reconstruction entirely -- the cached JSON *is*
            the response.
        """
        import json

        if self.document_repository is None:
            empty = build_knowledge_graph([])
            return {
                **_graph_to_json_dict(empty),
                "truncated": False,
                "total_document_count": 0,
                "hidden_document_count": 0,
            }

        cache_key = (
            f"documents:graph:{company_id}:{owner_id or 'all'}:{clearance.value}"
        )
        if self.cache is not None:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except (ValueError, TypeError):
                    logger.warning("Corpus graph cache entry for %s failed to parse.", cache_key)

        documents = await self.document_repository.list_for_owner(
            company_id, owner_id, skip=0, limit=MAX_GRAPH_DOCUMENTS
        )
        total_document_count = await self.document_repository.count_for_owner(
            company_id, owner_id
        )

        entries: list[DocumentGraphInput] = []
        hidden_document_count = 0
        for document in documents:
            try:
                level = SensitivityLevel(document.sensitivity_level)
            except ValueError:
                level = SensitivityLevel.UNMARKED
            if level > clearance:
                hidden_document_count += 1
                continue

            analysis = await self.get_cached_analysis(document.id)
            if analysis is None:
                entries.append(
                    DocumentGraphInput(
                        storage_path=document.id,
                        file_name=document.file_name,
                        document_type_label=document.document_type_label,
                        compliance_status=document.compliance_status,
                        has_analysis=False,
                    )
                )
                continue

            entries.append(
                DocumentGraphInput(
                    storage_path=document.id,
                    file_name=document.file_name,
                    document_type_label=document.document_type_label,
                    compliance_status=document.compliance_status,
                    has_analysis=True,
                    missing_fields=self._analysis_to_missing_field_inputs(analysis),
                    mevzuat_references=self._analysis_to_mevzuat_reference_inputs(analysis),
                    **self._analysis_to_entity_source_kwargs(analysis),
                )
            )

        graph = build_knowledge_graph(entries)
        result = {
            **_graph_to_json_dict(graph),
            "truncated": total_document_count > MAX_GRAPH_DOCUMENTS,
            "total_document_count": total_document_count,
            "hidden_document_count": hidden_document_count,
        }

        if self.cache is not None:
            await self.cache.set(
                cache_key, json.dumps(result, default=str), expire_seconds=GRAPH_CACHE_TTL_SECONDS
            )

        return result

    async def build_document_graph(self, storage_path: str) -> Optional[dict[str, Any]]:
        """Build the single-document neighbourhood: one document and every
        madde/kanun it touches, via the exact same builder `build_corpus_graph`
        uses over the whole corpus.

        Args:
            storage_path: The document's storage key.

        Returns:
            The same dict shape `build_corpus_graph` returns (minus the
            corpus-only `truncated`/`total_document_count`/
            `hidden_document_count` keys), or `None` when no cached analysis
            exists -- the router turns that into a 404, the same signal
            `get_cached_analysis` already uses.
        """
        analysis = await self.get_cached_analysis(storage_path)
        if analysis is None:
            return None

        entry = DocumentGraphInput(
            storage_path=storage_path,
            file_name=analysis.file_name,
            document_type_label=analysis.document_type_label,
            compliance_status=analysis.compliance_status.value,
            has_analysis=True,
            missing_fields=self._analysis_to_missing_field_inputs(analysis),
            mevzuat_references=self._analysis_to_mevzuat_reference_inputs(analysis),
            **self._analysis_to_entity_source_kwargs(analysis),
        )
        graph = build_knowledge_graph([entry])
        return _graph_to_json_dict(graph)

    async def get_document_text(
        self, storage_path: str
    ) -> Optional[DocumentTextSchema]:
        """Return the extracted/OCR text of a previously analysed document.

        Backs the "view OCR text" panel section. The text has always been
        persisted -- ``_save_document_analysis_cache`` writes
        ``extracted_text``/``pages`` as sibling keys to ``"analysis"`` on
        every analyze/update -- it was just never exposed through any
        endpoint before this, since ``get_cached_analysis`` deliberately
        returns only the ``"analysis"`` key.

        Args:
            storage_path: The document's storage key.

        Returns:
            The cached pages/text plus extraction provenance, or None if no
            cache exists for ``storage_path`` (or it fails to parse) -- the
            same "not found" signal every other cache-reading method here
            uses, which the router maps to a 404.
        """
        cache_data = await self._read_analysis_cache(storage_path)
        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        return DocumentTextSchema(
            pages=cache_data.get("pages", []),
            extracted_text=cache_data.get("extracted_text", ""),
            page_count=analysis.extraction.page_count,
            extractor=analysis.extraction.extractor,
            used_ocr=analysis.extraction.used_ocr,
        )

    async def update_document_text(
        self, storage_path: str, pages: list[str], company_id: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Apply hand-corrected OCR/extraction text and deterministically
        re-derive everything downstream of it -- no model call.

        The companion to the extraction-acceptance fix in
        `FallbackDocumentExtractor`: a user looking at text the automatic
        pipeline still got wrong (or that fell below the field-recovery
        floor and was never escalated) can fix it directly. Re-derivation
        mirrors `update_document_fields`'s cache-mutation shape, but text
        first rather than fields first: `parse_labelled_fields` +
        `merge_parsed_over_model` recompute `fields` from the corrected
        text exactly as `analyze_node` does, `check_required_fields`
        re-runs the same deterministic rule table, and
        `app.ai.guardrails.sensitivity.assess` re-derives sensitivity/PII --
        all pure functions, all synchronous, all already in this codebase.
        Deliberately NOT a full `_run_analysis` re-run: that costs ~110s and
        can re-classify the document from text the user only partially
        fixed, whereas every step here costs microseconds. `summary`,
        `detailed_summary` and `mevzuat_references` are left describing the
        pre-correction text -- the same trade `update_document_fields`
        already makes; the frontend surfaces a note and the existing
        detailed-summary endpoint is the re-trigger.

        Args:
            storage_path: The document's storage key.
            pages: The corrected page texts. Must have the same length as
                the cached document's page count -- `PageMap`,
                `get_document_outline`/`get_document_section` and
                `signature.marks[].page` all index by page number, so a
                silently different page count would desync every one of
                them.
            company_id: The caller's company, used the same way
                `update_document_fields` uses it -- to touch up the
                registry row's `compliance_status` after re-derivation.

        Returns:
            The updated analysis, or None if no cache exists for
            `storage_path` (or it fails to parse).

        Raises:
            ValidationException: If `len(pages)` does not match the cached
                document's page count.
        """
        cache_data = await self._read_analysis_cache(storage_path)
        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        cached_page_count = len(cache_data.get("pages") or [])
        if len(pages) != cached_page_count:
            raise ValidationException(
                message="Sayfa sayısı önbellekteki belgeyle eşleşmiyor.",
                details={
                    "expected_page_count": cached_page_count,
                    "got_page_count": len(pages),
                },
            )

        extracted_text, scrubbed_pages, _ = self._rederive_from_pages(analysis, pages)
        await self._save_rederived_analysis(
            storage_path, extracted_text, scrubbed_pages, analysis, company_id
        )
        return analysis

    def _rederive_from_pages(
        self, analysis: DocumentAnalysisResponseSchema, pages: list[str]
    ) -> tuple[str, list[str], list[str]]:
        """Scrub, re-parse and re-derive fields/compliance/sensitivity from
        page text -- the deterministic core shared by `update_document_text`
        (hand-corrected text) and `reextract_document_text` (freshly
        re-OCR'd text). No model call in either case.

        Mutates `analysis` in place: `fields`, `missing_fields`,
        `compliance_status`, `extraction.char_count`,
        `extraction.scrubbed_markers` and `guardrail`. Leaves
        `extraction.extractor`/`used_ocr`/`page_count` untouched -- callers
        that changed provenance (only `reextract_document_text` does) set
        those themselves before calling this.

        Args:
            analysis: The analysis to mutate. Its `document_type` decides
                which required-field rule table `check_required_fields`
                applies.
            pages: Page texts to derive everything from.

        Returns:
            `(extracted_text, scrubbed_pages, scrubbed_markers)` -- the
            join, the per-page scrubbed text, and every injection marker
            found, in that order, for the caller to persist.
        """
        # Attacker-controlled input exactly like an upload is -- scrub per
        # page, never the already-joined text, so char offsets stay
        # consistent with what PageMap/chunking compute from these same
        # pages (see analyze_document's identical reasoning).
        scrubbed_pages: list[str] = []
        scrubbed_markers: list[str] = []
        for page_text in pages:
            cleaned, markers = scrub_extracted_text(page_text)
            scrubbed_pages.append(cleaned)
            scrubbed_markers.extend(markers)
        extracted_text = "\n\n".join(scrubbed_pages)

        parsed = parse_labelled_fields(extracted_text)
        merged_fields = merge_parsed_over_model(
            analysis.fields.model_dump(), parsed, document_text=extracted_text
        )
        analysis.fields = EvrakField(**merged_fields)

        report = check_required_fields(analysis.document_type, analysis.fields)
        analysis.missing_fields = report.missing_fields
        analysis.compliance_status = report.status

        analysis.extraction.char_count = len(extracted_text.strip())
        analysis.extraction.scrubbed_markers = scrubbed_markers

        assessment = assess_sensitivity(
            fields=analysis.fields, text=extracted_text, scrub_markers=scrubbed_markers
        )
        analysis.guardrail = GuardrailAssessmentSchema(
            sensitivity_level=assessment.level,
            effective_sensitivity_level=assessment.effective_level,
            sensitivity_is_defaulted=assessment.is_defaulted,
            pii_findings=[
                PiiFindingSchema(kind=finding.kind, preview=finding.preview)
                for finding in assessment.pii_findings
            ],
            requires_human_review=assessment.requires_review,
            reasons=assessment.reasons,
        )

        return extracted_text, scrubbed_pages, scrubbed_markers

    async def _save_rederived_analysis(
        self,
        storage_path: str,
        extracted_text: str,
        scrubbed_pages: list[str],
        analysis: DocumentAnalysisResponseSchema,
        company_id: str,
    ) -> None:
        """Persist a re-derived analysis and keep the Q&A index in sync.

        Shared save + registry touch-up + reindex tail for
        `update_document_text` and `reextract_document_text`.
        """
        await self._save_document_analysis_cache(
            storage_path, extracted_text, scrubbed_pages, analysis
        )

        if self.document_repository is not None:
            document = await self.document_repository.get_by_id(storage_path, company_id)
            if document is not None:
                document.compliance_status = analysis.compliance_status.value

        # _index_for_qa deletes any chunks already indexed under
        # storage_path before upserting the new ones (see its own
        # docstring), so the stale, pre-correction passages don't stay
        # retrievable alongside the corrected ones -- no separate delete
        # needed here.
        await self._index_for_qa(
            storage_path,
            extracted_text,
            scrubbed_pages,
            sensitivity_level=analysis.guardrail.effective_sensitivity_level,
        )

    async def reextract_document_text(
        self, storage_path: str, company_id: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Re-run OCR with the vision model directly, bypassing the
        extraction chain entirely -- the user's manual override for when
        `FallbackDocumentExtractor`'s own automatic escalation (see
        `_has_enough_header_fields`) doesn't fire on its own.

        Deliberately calls `self.vision_extractor.extract(...)` directly
        rather than going through `self.extractor` (the fallback chain):
        the chain would just try Tesseract first and might accept it again
        for the same reason it did originally. Going straight to the vision
        model always pays the full glm-ocr cost, which is exactly what a
        user clicking "Yeniden OCR" is asking for. Re-reads the raw stored
        bytes (`self.storage.get_file`) -- no re-upload needed.

        Unlike `update_document_text`, this trusts the fresh extraction's
        own page count and provenance rather than validating against what
        was cached before: the whole point is that OCR is being redone, so
        the old page count is not authoritative here.

        Args:
            storage_path: The document's storage key.
            company_id: The caller's company, passed through to
                `_save_rederived_analysis` the same way
                `update_document_text` uses it.

        Returns:
            The updated analysis, or None if no cache exists for
            `storage_path` (or it fails to parse).

        Raises:
            DocumentExtractionError: If the vision model call itself fails.
        """
        cache_data = await self._read_analysis_cache(storage_path)
        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        content = await self.storage.get_file(storage_path)
        extracted = await self.vision_extractor.extract(content)

        analysis.extraction.extractor = extracted.extractor
        analysis.extraction.used_ocr = extracted.used_ocr
        analysis.extraction.page_count = extracted.page_count

        extracted_text, scrubbed_pages, _ = self._rederive_from_pages(
            analysis, extracted.pages
        )
        await self._save_rederived_analysis(
            storage_path, extracted_text, scrubbed_pages, analysis, company_id
        )
        return analysis

    async def generate_detailed_summary(
        self, storage_path: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Build (or return the already-built) detailed summary for a
        previously analysed document.

        On-demand, not eager: `analyze_document` never calls this.
        Detailed summarization used to run as a graph branch on every
        upload, but measured directly it was the slowest thing in the whole
        pipeline (184-288s, against every other branch's <100s) -- see
        `create_document_analysis_graph`'s own docstring for the full
        reasoning. This is triggered by its own endpoint instead, so the
        cost is only ever paid when a user actually wants the result.

        Follows the exact same cache-mutation shape as
        `update_document_fields`: read the cache file -> None if absent or
        invalid -> mutate only the field this method owns -> re-save,
        passing `extracted_text`/`pages` straight back through so they
        survive the rewrite untouched. Two things fall out of that shape:

        - No re-extraction. The summary is built from the text already
          cached by `_save_document_analysis_cache` -- no OCR, no vision
          model, no re-upload.
        - Idempotent. If `analysis.detailed_summary` is already set (a
          previous call already built it), this returns immediately without
          another model call -- a second click, or a page reload, costs
          nothing.

        Args:
            storage_path: The document's storage key.

        Returns:
            The analysis with `detailed_summary` populated, or None if no
            cache exists for `storage_path` (or it fails to parse) -- the
            same "not found" signal `update_document_fields` uses, which the
            router maps to a 404.

        Raises:
            AIException: If building the summary times out or the
                underlying provider call fails. Raised, not swallowed --
                unlike a failure inside the old graph branch, which
                degraded silently to the short summary because the rest of
                the analysis had to succeed regardless, this method's only
                job is the summary itself, so a user who explicitly asked
                for it needs to know it did not arrive. The cache file is
                untouched either way: the write only happens after a
                successful build.
        """
        cache_data = await self._read_analysis_cache(storage_path)

        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        if analysis.detailed_summary:
            return analysis

        try:
            detailed_summary = await asyncio.wait_for(
                build_detailed_summary(
                    self.summarizer_agent,
                    cache_data.get("extracted_text", ""),
                    is_ocr_text=analysis.extraction.used_ocr,
                ),
                timeout=settings.DETAILED_SUMMARY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Detaylı özet oluşturma zaman aşımına uğradı.",
                details={"timeout_seconds": settings.DETAILED_SUMMARY_TIMEOUT_SECONDS},
            ) from exc
        except Exception as exc:
            logger.exception("Detailed summary generation failed for %s", storage_path)
            raise AIException(
                message="Detaylı özet oluşturulurken bir hata oluştu.",
                details={"reason": str(exc)},
            ) from exc

        analysis.detailed_summary = detailed_summary

        await self._save_document_analysis_cache(
            storage_path,
            cache_data.get("extracted_text", ""),
            cache_data.get("pages", []),
            analysis,
        )

        return analysis

    async def _extract_with_vision_cascade(self, content: bytes) -> ExtractedDocument:
        """Vision OCR, llm-fast first, escalating to llm-large if the fast
        tier either fails outright or its result doesn't clear the same
        acceptance bar `FallbackDocumentExtractor._is_acceptable` uses.

        The fast-tier call is wrapped in its own try/except specifically
        because it's a hard dependency on a single upstream model group --
        if that group has an outage (observed in production: Evren's own
        `llm-fast` backend unreachable), letting the exception propagate
        would make this feature entirely unusable even though `llm-large`
        is healthy and could serve every request on its own. A quality-bar
        miss and an outright failure both fall through to the same
        escalation call below; only the log line distinguishes them.

        Ollama has no equivalent fast/large split (a single
        `OLLAMA_VISION_MODEL`), so `LOCAL_MODE=true` always uses
        `self.vision_extractor` directly, same single-tier call
        `reextract_document_text` already makes.

        Args:
            content: Raw document bytes.

        Returns:
            The extraction result -- from the fast tier if it was
            available and good enough, otherwise from the large-tier
            escalation.
        """
        if settings.LOCAL_MODE or not isinstance(self.vision_extractor, EvrenVisionExtractor):
            return await self.vision_extractor.extract(content)

        try:
            fast_result = await self.vision_extractor.extract(content)
        except DocumentExtractionError:
            logger.warning(
                "Detailed analysis: llm-fast vision call failed outright; "
                "escalating to llm-large without a quality comparison.",
                exc_info=True,
            )
            fast_result = None

        if fast_result is not None:
            if (
                fast_result.char_count >= MIN_EXTRACTED_CHAR_COUNT
                and fast_result.quality_ratio >= MIN_TEXT_QUALITY_RATIO
            ):
                return fast_result
            logger.info(
                "Detailed analysis: llm-fast vision result below the quality bar "
                "(char_count=%d, quality_ratio=%.2f); escalating to llm-large.",
                fast_result.char_count,
                fast_result.quality_ratio,
            )
        return await EvrenVisionExtractor(model=settings.EVREN_LLM_LARGE_MODEL).extract(content)

    async def generate_detailed_analysis(
        self, storage_path: str, company_id: str
    ) -> Optional[DocumentAnalysisResponseSchema]:
        """Re-run extraction via vision OCR (see `_extract_with_vision_cascade`)
        and the full analysis graph -- unlike `reextract_document_text`
        (deterministic field re-derivation only, no model call) and
        `generate_detailed_summary` (only the long summary), this replaces
        `document_type`/`summary`/every field/`compliance_status`/mevzuat
        references: the complete result a fresh upload would have produced
        had OCR actually run.

        On-demand only: vision OCR is no longer part of the default upload
        path (see `get_document_extractor`'s own docstring for why -- a
        single upload was measured to go from ~14s to ~34s whenever the old
        chain's automatic repair triggered). This is the escape hatch for a
        user who wants the thorough, accurate-but-slow result on demand.

        Args:
            storage_path: The document's storage key.
            company_id: The caller's company -- passed through to
                `_run_analysis` (Langfuse trace metadata) and
                `_save_rederived_analysis` (registry row + Q&A reindex),
                same as `reextract_document_text`.

        Returns:
            The freshly re-analysed result, or None if no cache exists for
            `storage_path` (or it fails to parse) -- the router maps this
            to a 404, same as `generate_detailed_summary`.

        Raises:
            AIException: If the vision cascade or the analysis workflow
                times out or fails. Raised, not swallowed -- a user who
                explicitly asked for this needs to know it did not arrive.
                The cache file is untouched until a full new analysis is
                ready to replace it.
        """
        cache_data = await self._read_analysis_cache(storage_path)
        if not cache_data or not cache_data.get("analysis"):
            return None

        try:
            previous_analysis = DocumentAnalysisResponseSchema(**cache_data["analysis"])
        except Exception:
            logger.exception("Cached analysis for %s failed to validate", storage_path)
            return None

        content = await self.storage.get_file(storage_path)

        try:
            extracted = await asyncio.wait_for(
                self._extract_with_vision_cascade(content),
                timeout=settings.DETAILED_ANALYSIS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise AIException(
                message="Detaylı analiz zaman aşımına uğradı.",
                details={"timeout_seconds": settings.DETAILED_ANALYSIS_TIMEOUT_SECONDS},
            ) from exc
        except DocumentExtractionError as exc:
            raise AIException(
                message="Detaylı analiz sırasında belge işlenemedi.",
                details={"reason": str(exc)},
            ) from exc

        # Same reasoning as analyze_document: attacker-controlled input,
        # scrubbed per page before anything downstream reads it.
        scrubbed_pages: list[str] = []
        scrubbed_markers: list[str] = []
        for page_text in extracted.pages or [extracted.text]:
            cleaned, markers = scrub_extracted_text(page_text)
            scrubbed_pages.append(cleaned)
            scrubbed_markers.extend(markers)
        extracted.pages = scrubbed_pages
        extracted.text = "\n\n".join(scrubbed_pages)

        state = await self._run_analysis(
            extracted.text, extracted.used_ocr, extracted.detected_marks, company_id=company_id
        )
        analysis = self._assemble(
            previous_analysis.file_name, storage_path, extracted, state, scrubbed_markers
        )
        # detailed_summary is owned by generate_detailed_summary, not
        # recomputed here -- carry over whatever was already built, same
        # as a fresh analyze_document response never setting it either.
        analysis.detailed_summary = previous_analysis.detailed_summary

        await self._save_rederived_analysis(
            storage_path, extracted.text, extracted.pages, analysis, company_id
        )
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

        try:
            await self.storage.delete_file(_analysis_cache_key(storage_path))
        except Exception:
            logger.exception("Failed to delete cached analysis for %s", storage_path)

        if self.vector_store is not None:
            try:
                await self.vector_store.delete_by_filter(
                    QA_COLLECTION_NAME, {"storage_path": storage_path}
                )
            except Exception:
                logger.exception("Failed to delete indexed chunks for %s", storage_path)

    async def adopt_pool_item(
        self, *, item_id: str, current_user: UserModel, company_id: str
    ) -> DocumentPoolItemModel:
        """Copy-on-write for a transferred document (Faz 5, #205).

        Until this runs, a `source="transfer"` pool item's `document_id`
        still points at the *sender's* original `documents` row (see
        `app.domains.pools.service.PoolService.file_transferred_document`)
        -- the recipient can view it through the pool join but does not own
        it: they cannot edit its metadata, and it fails any ownership check
        keyed off `documents.owner_id`. This gives the pool item's own
        owner a fully independent copy instead: own blob (copied through
        `BaseStorage`, not assumed to be a bare local path -- see
        `BaseStorage`'s own docstring on why S3 keys aren't), own
        `documents` row, own analysis cache, reindexed for Q&A under the
        new storage key. See the plan's own §D5/§M for why the transfer
        itself deliberately stops short of this and leaves `adopt` as an
        opt-in escape hatch rather than doing it automatically on every
        transfer (most recipients never need to edit what they received).

        Reindexing runs inline, synchronously -- the same way the original
        upload path's own `_index_for_qa` already does. There is no
        arq-backed indexing worker in this codebase to queue onto instead
        (the only wired-up arq job today is LoRA training, see
        `app.workers.queue.WorkerSettings`); standing one up is out of
        scope for what is otherwise a same-shape copy operation.

        Raises:
            NotFoundException: The pool item, its pool, or the source
                document doesn't resolve within `company_id`.
            AuthorizationException: The caller isn't the pool's own owner
                -- unlike most of this module's authorization, there is no
                Admin/Manager bypass here, since adopting creates a
                *personal* copy for the caller specifically.
            ValidationException: The item isn't a `source="transfer"` item
                (nothing else needs adopting), or the source file itself
                can't be read back from storage.
        """
        if self.pool_item_repository is None or self.pool_repository is None or self.document_repository is None:
            raise ValidationException(message="Evrak havuzu bu istek için yapılandırılmamış.")

        item = await self.pool_item_repository.get_by_id(item_id, company_id)
        if item is None:
            raise NotFoundException(message="Havuz öğesi bulunamadı.")

        pool = await self.pool_repository.get_by_id(item.pool_id, company_id)
        if pool is None or pool.owner_type != "user" or pool.owner_id != current_user.id:
            raise AuthorizationException(message="Bu öğeyi yalnızca havuzun sahibi kopyalayabilir.")

        if item.source != "transfer":
            raise ValidationException(message="Yalnızca transfer edilen evraklar bu şekilde kopyalanabilir.")

        source_document = await self.document_repository.get_by_id(item.document_id, company_id)
        if source_document is None:
            raise NotFoundException(message="Kaynak evrak bulunamadı.")

        if self.quota_service is not None:
            await self.quota_service.check_and_increment(company_id, DOCUMENTS_METRIC)

        try:
            content = await self.storage.get_file(source_document.id)
        except Exception as exc:
            raise ValidationException(message="Kaynak evrak dosyasına ulaşılamadı.") from exc

        new_storage_path = await self._store(source_document.file_name, content)

        # The snapshot frozen at transfer time (see `file_transferred_
        # document`) is the most up to date view the recipient actually
        # saw -- falling back to the sender's live row only covers the
        # (should-never-happen) case of an item.source="transfer" row with
        # no snapshot.
        snapshot = item.metadata_snapshot or {}
        new_document = DocumentModel(
            id=new_storage_path,
            owner_id=current_user.id,
            company_id=company_id,
            file_name=source_document.file_name,
            document_type=snapshot.get("document_type", source_document.document_type),
            document_type_label=snapshot.get("document_type_label", source_document.document_type_label),
            compliance_status=snapshot.get("compliance_status", source_document.compliance_status),
            summary=snapshot.get("summary", source_document.summary),
            sensitivity_level=snapshot.get("sensitivity_level", source_document.sensitivity_level),
            pii_flagged=bool(snapshot.get("pii_flagged", source_document.pii_flagged)),
        )
        await self.document_repository.create(new_document)

        cache_data = await self._copy_analysis_cache(source_document.id, new_storage_path)
        if cache_data is not None:
            try:
                sensitivity_level = SensitivityLevel(new_document.sensitivity_level)
            except ValueError:
                sensitivity_level = SensitivityLevel.UNMARKED
            await self._index_for_qa(
                new_storage_path,
                cache_data.get("extracted_text", ""),
                cache_data.get("pages"),
                sensitivity_level=sensitivity_level,
            )

        # Repoint the existing item at the new, owned copy rather than
        # creating a second pool item -- the recipient still has exactly
        # one entry for this document, now backed by their own row instead
        # of a snapshot. `transferred_by` is left as-is: who originally
        # sent it is still true and worth keeping after adoption, even
        # though `source` no longer reads "transfer".
        item.document_id = new_storage_path
        item.source = "adopted"
        item.metadata_snapshot = None
        await self.pool_item_repository.save(item)

        slug = company_metrics.cached_slug(company_id)
        if slug is not None:
            company_metrics.note_document_registered(slug)

        return item

    async def _copy_analysis_cache(
        self, source_storage_path: str, new_storage_path: str
    ) -> Optional[dict]:
        """Copy the analysis-cache JSON under a new storage key, for
        `adopt_pool_item` -- the cache is keyed by storage_path (see
        `_save_document_analysis_cache`), so an adopted copy needs its own
        cache entry too, not just the blob.

        Returns:
            The copied cache dict (so the caller can reindex immediately
            without a second read), or `None` when the source had no
            cache to copy -- a degraded but non-fatal case (adopt still
            succeeds, just without Q&A indexing), the same "best-effort
            past the registry row" tolerance `delete_document` already
            applies to its own cleanup steps.
        """
        try:
            content = await self.storage.get_file(_analysis_cache_key(source_storage_path))
        except FileNotFoundError:
            return None
        except Exception:
            logger.exception(
                "Failed to copy analysis cache from %s to %s", source_storage_path, new_storage_path
            )
            return None

        try:
            data = json.loads(content)
            await self.storage.put_file(_analysis_cache_key(new_storage_path), content)
        except Exception:
            logger.exception(
                "Failed to copy analysis cache from %s to %s", source_storage_path, new_storage_path
            )
            return None
        return data
