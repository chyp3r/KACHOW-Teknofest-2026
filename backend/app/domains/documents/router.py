import asyncio
import json
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile

from app.ai.workflows.correspondence import CORRESPONDENCE_TYPE_LABELS
from app.api.dependency import get_document_analysis_service, get_draft_service, require_auth_if_enabled
from app.api.exceptions.validation import ValidationException
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.core.config import settings
from app.core.constants import MAX_FILE_SIZE_BYTES
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.schema.document_schema import DraftRequestSchema
from app.shared.dto.pagination import PaginatedResponse, PaginationParam
from app.shared.validator.storage_path_validator import validate_storage_path

# dependencies=[...] applies to every route in this router: see
# require_auth_if_enabled and settings.REQUIRE_AUTH for why this is a no-op
# by default rather than always-on.
router = APIRouter(
    prefix="/documents", tags=["documents"], dependencies=[Depends(require_auth_if_enabled)]
)

#: Read in 1 MiB chunks so the running total can be checked against the limit
#: before the next chunk is even requested from the client.
_READ_CHUNK_BYTES = 1 << 20


async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read an UploadFile's body without ever materialising more than ``limit``.

    ``await file.read()`` reads the entire body into memory before any size
    check can run -- a 2GB upload allocates 2GB regardless of the configured
    50MB limit, since the limit was only ever checked afterwards. This raises
    the moment the running total crosses ``limit``, so worst-case memory stays
    bounded by ``limit + _READ_CHUNK_BYTES``.

    Args:
        file: The incoming upload.
        limit: Maximum allowed size in bytes.

    Returns:
        The full file content, guaranteed to be at most ``limit`` bytes.

    Raises:
        ValidationException: If the body exceeds ``limit``.
    """
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValidationException(
                message="Yüklenen dosya izin verilen azami boyutu aşıyor.",
                details={"max_size_bytes": limit},
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/analyze", response_model=None)
async def analyze_document(
    http_request: Request,
    file: UploadFile = File(..., description="Analiz edilecek evrak dosyası."),
    service: DocumentService = Depends(get_document_analysis_service),
    _: None = Depends(rate_limit(max_requests=10, window_seconds=60, key_prefix="documents:analyze")),
):
    """Perform the first review (ön inceleme) of an incoming official document.

    Reads the document via direct text extraction or OCR, determines its type,
    extracts its header fields, reports required-but-missing information with the
    relevant legislation, and returns a short summary.

    Args:
        http_request: The raw request, checked for a declared Content-Length
            before the body is read at all.
        file: The uploaded document.
        service: Injected document analysis service.

    Returns:
        The analysis result inside the unified success envelope.
    """
    declared_length = http_request.headers.get("content-length")
    if declared_length is not None and declared_length.isdigit():
        if int(declared_length) > MAX_FILE_SIZE_BYTES:
            raise ValidationException(
                message="Yüklenen dosya izin verilen azami boyutu aşıyor.",
                details={"max_size_bytes": MAX_FILE_SIZE_BYTES},
            )

    content = await _read_bounded(file, MAX_FILE_SIZE_BYTES)
    result = await service.analyze_document(
        file_name=file.filename or "evrak",
        content=content,
        content_type=file.content_type,
    )
    # mode="json" is required: the response envelope is serialised with json.dumps,
    # which cannot handle nested Pydantic models or enum members.
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.post("/draft", response_model=None)
async def generate_draft(
    request: DraftRequestSchema,
    service: DraftService = Depends(get_draft_service),
):
    """Generate an official draft and department routing suggestion (Task 2).

    Uses the output from the first review (Görev 1) to determine the correct
    correspondence type, draft the text, and route it to the appropriate department.
    """
    result = await service.generate_draft_and_route(request)
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("", response_model=None)
async def list_documents(pagination: PaginationParam = Depends()):
    """List uploaded documents with their summary metadata, newest first.

    Args:
        pagination: Page/size query parameters.

    Returns:
        A paginated envelope over the 7-field library projection (see
        ``GET /documents/{storage_path}`` for the full analysis).
    """
    metadata_file = os.path.join(settings.LOCAL_STORAGE_DIR, "uploads_metadata.json")

    def _read() -> list[dict]:
        if not os.path.exists(metadata_file):
            return []
        with open(metadata_file, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        # json.load on a synchronous file handle blocks the event loop for
        # every list call; the library grows without bound as documents are
        # uploaded, so this was not a one-time cost.
        data = await asyncio.to_thread(_read)
    except Exception:
        data = []

    data.sort(key=lambda item: item.get("upload_time", ""), reverse=True)

    total = len(data)
    page_items = data[pagination.offset : pagination.offset + pagination.limit]
    pages = (total + pagination.size - 1) // pagination.size if pagination.size else 0

    return SuccessResponse(
        data=PaginatedResponse(
            items=page_items,
            total=total,
            page=pagination.page,
            size=pagination.size,
            pages=pages,
        ).model_dump()
    )


@router.get("/correspondence-types", response_model=None)
async def list_correspondence_types():
    """List the supported outbound correspondence types and their Turkish labels.

    Single source of truth for the frontend's type selector, instead of the
    labels being retyped in TypeScript and drifting from
    ``app.ai.workflows.correspondence.CORRESPONDENCE_TYPE_LABELS``.
    """
    return SuccessResponse(
        data=[
            {"value": correspondence_type.value, "label": label}
            for correspondence_type, label in CORRESPONDENCE_TYPE_LABELS.items()
        ]
    )


@router.get("/{storage_path:path}", response_model=None)
async def get_document_analysis(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
):
    """Return a previously computed analysis in full.

    ``GET /documents`` only ever returns the 7-field library projection
    (document_type_label, compliance_status, summary, ...); re-selecting a
    document from that list lost ``missing_fields`` and
    ``mevzuat_references`` entirely because nothing exposed the cached
    analysis this reads back.

    Args:
        storage_path: The document's storage key (as returned by
            ``POST /documents/analyze``).
        service: Injected document analysis service.

    Returns:
        The full analysis inside the unified success envelope.

    Raises:
        HTTPException: 400 if storage_path is malformed, 404 if no analysis
            is cached for it.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = await service.get_cached_analysis(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    return SuccessResponse(data=result.model_dump(mode="json"))
