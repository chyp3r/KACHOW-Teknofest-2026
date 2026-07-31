from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependency import get_document_analysis_service, get_draft_service
from app.api.responses import SuccessResponse
from app.domains.documents.service import DocumentService
from app.domains.documents.draft_service import DraftService
from app.domains.documents.schema.document_schema import DraftRequestSchema

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/analyze", response_model=None)
async def analyze_document(
    file: UploadFile = File(..., description="Analiz edilecek evrak dosyası."),
    service: DocumentService = Depends(get_document_analysis_service),
):
    """Perform the first review (ön inceleme) of an incoming official document.

    Reads the document via direct text extraction or OCR, determines its type,
    extracts its header fields, reports required-but-missing information with the
    relevant legislation, and returns a short summary.

    Args:
        file: The uploaded document.
        service: Injected document analysis service.

    Returns:
        The analysis result inside the unified success envelope.
    """
    content = await file.read()
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
async def list_documents():
    """List all uploaded documents with their metadata."""
    import json
    import os
    from app.core.config import settings

    metadata_file = os.path.join(settings.LOCAL_STORAGE_DIR, "uploads_metadata.json")
    if not os.path.exists(metadata_file):
        return SuccessResponse(data=[])

    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Sort by upload time descending (newest first)
        data.sort(key=lambda x: x.get("upload_time", ""), reverse=True)
        return SuccessResponse(data=data)
    except Exception:
        return SuccessResponse(data=[])
