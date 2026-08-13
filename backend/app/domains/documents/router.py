from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.ai.workflows.correspondence import CORRESPONDENCE_TYPE_LABELS
from app.api.dependency import (
    get_document_analysis_service,
    get_document_repository,
    get_draft_service,
    require_auth_if_enabled,
)
from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.validation import ValidationException
from app.api.rate_limit import rate_limit
from app.api.responses import SuccessResponse
from app.core.authz.attributes import Action, Resource
from app.core.authz.dependency import subject_from_user
from app.core.authz.engine import authorize
from app.core.constants import MAX_FILE_SIZE_BYTES
from app.core.enums.sensitivity_level import SensitivityLevel
from app.core.permissions.role_checker import assert_clearance, bypasses_ownership
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.repository import DocumentRepository
from app.domains.documents.schema.document_schema import (
    DocumentFieldsUpdateSchema,
    DraftRequestSchema,
)
from app.domains.users.model.user_model import UserModel
from app.shared.dto.pagination import PaginatedResponse, PaginationParam
from app.shared.validator.storage_path_validator import validate_storage_path

# dependencies=[...] applies to every route in this router -- authentication
# is mandatory (see require_auth_if_enabled), so every request here carries
# a real, tenant-bound current_user.
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


def _authorize_document(current_user: UserModel, document: DocumentModel, action: str) -> None:
    """Single ABAC decision replacing the ``owner_id``/``bypasses_ownership``
    check every route below used to repeat inline.

    Calls the bare, grant-less ``engine.authorize`` (built-in role rules
    only) rather than the DB-backed ``AuthzService``: reproduces
    ``bypasses_ownership``'s exact prior semantics (ADMIN/MANAGER/ROOT see
    every document company-wide, EMPLOYEE only its own), with zero new
    per-request DB/Redis round trips on this hot path. Consulting
    ``permission_grants`` here too is a natural follow-up once a caller
    actually needs to delegate document access beyond role, not a gap in
    this change -- see the Faz 2 issue.

    Raises:
        AuthorizationException: If ``authorize()`` denies.
    """
    resource = Resource(
        type="document", id=document.id, company_id=document.company_id, owner_id=document.owner_id
    )
    decision = authorize(subject_from_user(current_user), action, resource)
    if not decision.permit:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")


@router.post("/analyze", response_model=None)
async def analyze_document(
    http_request: Request,
    file: UploadFile = File(..., description="Analiz edilecek evrak dosyası."),
    service: DocumentService = Depends(get_document_analysis_service),
    current_user: UserModel = Depends(require_auth_if_enabled),
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
        current_user: The authenticated caller -- registered as the
            document's owner and company so later reads can be restricted
            to them.

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
        owner_id=current_user.id,
        company_id=current_user.company_id,
    )
    # mode="json" is required: the response envelope is serialised with json.dumps,
    # which cannot handle nested Pydantic models or enum members.
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.post("/draft", response_model=None)
async def generate_draft(
    request: DraftRequestSchema,
    service: DraftService = Depends(get_draft_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Generate an official draft and department routing suggestion (Task 2).

    Uses the output from the first review (Görev 1) to determine the correct
    correspondence type, draft the text, and route it to the appropriate department.

    ``DraftService`` reads the source document straight from storage by
    ``storage_path`` -- unlike ``GET /documents/{storage_path}``, it has no
    ownership/clearance concept of its own, so that check belongs here, at
    the router boundary, before the raw file content ever reaches the
    drafting graph.

    Raises:
        AuthorizationException: If the document belongs to a different
            company, or a different owner than ``current_user`` (and it
            isn't ADMIN/MANAGER/ROOT), or ``current_user``'s clearance
            doesn't cover the document's confidentiality level.
    """
    document = await document_repository.get_by_id(request.storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)
    try:
        document_level = SensitivityLevel(document.sensitivity_level)
    except ValueError:
        document_level = SensitivityLevel.UNMARKED
    assert_clearance(current_user, document_level)

    result = await service.generate_draft_and_route(
        request, user_id=current_user.id, company_id=current_user.company_id
    )
    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("", response_model=None)
async def list_documents(
    pagination: PaginationParam = Depends(),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """List uploaded documents with their summary metadata, newest first.

    Args:
        pagination: Page/size query parameters.
        document_repository: Ownership/listing registry.
        current_user: The authenticated caller -- the list is restricted to
            documents it owns, unless it is ADMIN/MANAGER/ROOT (see
            ``bypasses_ownership``), who see every document company-wide.
            Never cross-company regardless of role.

    Returns:
        A paginated envelope over the 7-field library projection (see
        ``GET /documents/{storage_path}`` for the full analysis).
    """
    owner_id = None if bypasses_ownership(current_user) else current_user.id
    documents = await document_repository.list_for_owner(
        current_user.company_id, owner_id, skip=pagination.offset, limit=pagination.limit
    )
    total = await document_repository.count_for_owner(current_user.company_id, owner_id)

    page_items = [
        {
            "file_name": document.file_name,
            "storage_path": document.id,
            "upload_time": document.created_at.isoformat(),
            "document_type": document.document_type,
            "document_type_label": document.document_type_label,
            "compliance_status": document.compliance_status,
            "summary": document.summary,
        }
        for document in documents
    ]
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


@router.patch("/{storage_path:path}/fields", response_model=None)
async def update_document_fields(
    storage_path: str,
    payload: DocumentFieldsUpdateSchema,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Manually correct a document's extracted fields.

    UI-driven fix for fields the extraction missed or got wrong (see
    ``DocumentAnalysisPanel`` -- previously read-only). Re-runs the same
    deterministic compliance check the original analysis used
    (``app.ai.compliance.checker.check_required_fields``, no LLM call), so
    ``missing_fields``/``compliance_status`` reflect the correction
    immediately instead of staying stuck at whatever the extraction found.

    Args:
        storage_path: The document's storage key.
        payload: The full corrected field set.
        service: Injected document analysis service.
        document_repository: Ownership registry, checked before the update.
        current_user: The authenticated caller.

    Returns:
        The updated analysis, in the same shape as ``GET /documents/{storage_path}``.

    Raises:
        HTTPException: 400 if storage_path is malformed, 404 if no analysis
            is cached for it.
        AuthorizationException: 403 if the document belongs to a different
            company or user, or the requester's clearance doesn't cover the
            document's confidentiality level.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_UPDATE)

    result = await service.update_document_fields(storage_path, payload.fields, current_user.company_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.get("/{storage_path:path}", response_model=None)
async def get_document_analysis(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
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
        document_repository: Ownership registry, checked before returning
            content.
        current_user: The authenticated caller.

    Returns:
        The full analysis inside the unified success envelope.

    Raises:
        HTTPException: 400 if storage_path is malformed, 404 if no analysis
            is cached for it.
        AuthorizationException: 403 if the document belongs to a different
            company, or a different user than the one making the request
            (and it isn't ADMIN/MANAGER/ROOT), or the requester's clearance
            doesn't cover the document's confidentiality level.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is None:
        raise AuthorizationException(message="Bu evraka erişim izniniz yok.")
    _authorize_document(current_user, document, Action.DOCUMENT_READ)

    result = await service.get_cached_analysis(storage_path)
    if result is None:
        raise HTTPException(status_code=404, detail="Bu evrak için bir analiz bulunamadı.")

    assert_clearance(current_user, result.guardrail.sensitivity_level)

    return SuccessResponse(data=result.model_dump(mode="json"))


@router.delete("/{storage_path:path}", response_model=None)
async def delete_document(
    storage_path: str,
    service: DocumentService = Depends(get_document_analysis_service),
    document_repository: DocumentRepository = Depends(get_document_repository),
    current_user: UserModel = Depends(require_auth_if_enabled),
):
    """Permanently delete a document: registry row, raw file, analysis
    cache, and any indexed Q&A chunks.

    Args:
        storage_path: The document's storage key.
        service: Injected document analysis service.
        document_repository: Ownership/listing registry, checked before the
            delete.
        current_user: The authenticated caller.

    Returns:
        ``{"deleted": true}`` inside the unified success envelope. Succeeds
        even if ``storage_path`` was already gone -- delete is idempotent.

    Raises:
        HTTPException: 400 if storage_path is malformed.
        AuthorizationException: 403 if the document belongs to a different
            company, or a different user than ``current_user`` (and it
            isn't ADMIN/MANAGER/ROOT), or ``current_user``'s clearance
            doesn't cover the document's confidentiality level.
    """
    try:
        validate_storage_path(storage_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await document_repository.get_by_id(storage_path, current_user.company_id)
    if document is not None:
        _authorize_document(current_user, document, Action.DOCUMENT_DELETE)
        try:
            document_level = SensitivityLevel(document.sensitivity_level)
        except ValueError:
            document_level = SensitivityLevel.UNMARKED
        assert_clearance(current_user, document_level)

    await service.delete_document(storage_path, current_user.company_id)
    return SuccessResponse(data={"deleted": True})
