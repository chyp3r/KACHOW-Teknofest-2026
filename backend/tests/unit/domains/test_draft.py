import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.enums.reasoning_level import ReasoningLevel
from app.domains.documents.draft_service import DraftService
from app.domains.documents.schema.document_schema import DraftRequestSchema
from app.api.exceptions.validation import ValidationException
from app.api.exceptions.ai_error import AIException
from app.infrastructure.extractors.base import DocumentExtractionError, ExtractedDocument

#: Matches the shape DocumentService._store() produces --
#: uploads/<32 hex><ext> -- which is what validate_storage_path requires.
VALID_STORAGE_PATH = "uploads/" + "a" * 32 + ".pdf"


def _request(**overrides) -> DraftRequestSchema:
    fields = dict(
        storage_path=VALID_STORAGE_PATH,
        classification={"document_type": "petition"},
    )
    fields.update(overrides)
    return DraftRequestSchema(**fields)


@pytest.fixture
def mock_storage():
    storage = AsyncMock()
    storage.get_file.return_value = b"test pdf content"
    return storage


@pytest.fixture
def mock_extractor():
    extractor = AsyncMock()
    extracted = MagicMock(spec=ExtractedDocument)
    extracted.text = "This is the source document text."
    extractor.extract.return_value = extracted
    return extractor


@pytest.fixture
def mock_draft_graph():
    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "status": "COMPLETED",
        "draft": "Sayın İlgili, taslak metindir.",
        "confidence_score": 85.0,
        "requires_human_approval": False,
        "attempts": 1,
        "verification": {},
        "judge": {},
        "missing_information": [],
    }
    return graph


@pytest.fixture
def mock_routing_graph():
    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "final_destination": "HR",
        "justification": "Personel işlemleri ile ilgilidir.",
    }
    return graph


@pytest.fixture
def draft_service(mock_storage, mock_extractor, mock_draft_graph, mock_routing_graph):
    return DraftService(
        storage=mock_storage,
        extractor=mock_extractor,
        draft_graph=mock_draft_graph,
        routing_graph=mock_routing_graph,
    )


@pytest.mark.asyncio
async def test_generate_draft_and_route_success(draft_service, mock_draft_graph, mock_routing_graph):
    request = _request(instructions="Test", correspondence_type="cover_letter")

    response = await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")

    assert response.draft == "Sayın İlgili, taslak metindir."
    assert response.confidence_score == 85.0
    assert response.requires_human_approval is False
    assert response.destination == "HR"
    assert response.justification == "Personel işlemleri ile ilgilidir."

    mock_draft_graph.ainvoke.assert_called_once()
    mock_routing_graph.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_draft_flags_human_approval_when_routing_cannot_assign_a_unit(
    draft_service, mock_draft_graph, mock_routing_graph
):
    """Routing failing to confidently assign a unit (no more fake
    "İnsan Onayı Gerekli" unit -- see routing_graph.py) must still surface as
    requires_human_approval on the draft, OR'd with the draft-quality gate's
    own verdict rather than overwriting it."""
    mock_routing_graph.ainvoke.return_value = {
        "final_destination": None,
        "justification": "Model tanımlı birim listesi dışında bir yanıt verdi; insan onayına yönlendirildi.",
        "requires_human_approval": True,
    }
    request = _request()

    response = await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")

    assert response.destination == ""
    assert response.requires_human_approval is True


@pytest.mark.asyncio
async def test_generate_draft_skips_routing_when_information_is_missing(
    draft_service, mock_draft_graph, mock_routing_graph
):
    """A draft with unfilled placeholders must not be routed to a department --
    it needs the missing-information round trip first (see /chat/resume)."""
    mock_draft_graph.ainvoke.return_value = {
        "status": "NEEDS_INPUT",
        "draft": "Sayın [...], ...",
        "confidence_score": 40.0,
        "requires_human_approval": True,
        "attempts": 1,
        "verification": {},
        "judge": {},
        "missing_information": [
            {"key": "muhatap", "label": "Muhatap", "why": "Eksik", "example": None, "required": True}
        ],
    }
    request = _request()

    response = await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")

    assert response.missing_information
    assert response.destination == ""
    mock_routing_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_generate_draft_storage_error(draft_service, mock_storage):
    mock_storage.get_file.side_effect = Exception("Storage error")
    request = _request()

    with pytest.raises(ValidationException) as exc:
        await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")
    assert "bulunamadı" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_draft_extractor_error(draft_service, mock_extractor):
    mock_extractor.extract.side_effect = DocumentExtractionError("Extraction failed")
    request = _request()

    with pytest.raises(ValidationException) as exc:
        await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")
    assert "çıkarılamadı" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_draft_graph_failure(draft_service, mock_draft_graph):
    mock_draft_graph.ainvoke.return_value = {
        "status": "FAILED",
        "error": "Writer failed",
    }
    request = _request()

    with pytest.raises(AIException) as exc:
        await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")
    assert "üretilemedi" in str(exc.value)


def test_storage_path_rejects_malformed_value():
    with pytest.raises(ValueError):
        _request(storage_path="uploads/../../etc/passwd")


def test_draft_request_defaults_reasoning_level_to_balanced():
    request = _request()

    assert request.reasoning_level == ReasoningLevel.BALANCED


@pytest.mark.asyncio
async def test_generate_draft_threads_the_requested_reasoning_level_into_the_graph(
    draft_service, mock_draft_graph
):
    request = _request(reasoning_level="deep")

    await draft_service.generate_draft_and_route(request, user_id="user-1", company_id="company-1")

    graph_input = mock_draft_graph.ainvoke.call_args.args[0]
    assert graph_input["reasoning_level"] == "deep"
