import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domains.documents.draft_service import DraftService
from app.domains.documents.schema.document_schema import DraftRequestSchema
from app.api.exceptions.validation import ValidationException
from app.api.exceptions.ai_error import AIException
from app.infrastructure.extractors.base import DocumentExtractionError, ExtractedDocument


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
        "requires_human_approval": False
    }
    return graph


@pytest.fixture
def mock_routing_graph():
    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "final_destination": "HR",
        "justification": "Personel işlemleri ile ilgilidir."
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
    request = DraftRequestSchema(
        storage_path="uploads/test.pdf",
        classification={"document_type": "Dilekçe"},
        instructions="Test",
        correspondence_type="cover_letter"
    )
    
    response = await draft_service.generate_draft_and_route(request)
    
    assert response.draft == "Sayın İlgili, taslak metindir."
    assert response.confidence_score == 85.0
    assert response.requires_human_approval is False
    assert response.destination == "HR"
    assert response.justification == "Personel işlemleri ile ilgilidir."
    
    mock_draft_graph.ainvoke.assert_called_once()
    mock_routing_graph.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_generate_draft_storage_error(draft_service, mock_storage):
    mock_storage.get_file.side_effect = Exception("Storage error")
    request = DraftRequestSchema(
        storage_path="uploads/invalid.pdf",
        classification={},
    )
    with pytest.raises(ValidationException) as exc:
        await draft_service.generate_draft_and_route(request)
    assert "bulunamadı" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_draft_extractor_error(draft_service, mock_extractor):
    mock_extractor.extract.side_effect = DocumentExtractionError("Extraction failed")
    request = DraftRequestSchema(
        storage_path="uploads/test.pdf",
        classification={},
    )
    with pytest.raises(ValidationException) as exc:
        await draft_service.generate_draft_and_route(request)
    assert "çıkarılamadı" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_draft_graph_failure(draft_service, mock_draft_graph):
    mock_draft_graph.ainvoke.return_value = {
        "status": "FAILED",
        "error": "Writer failed"
    }
    request = DraftRequestSchema(
        storage_path="uploads/test.pdf",
        classification={},
    )
    with pytest.raises(AIException) as exc:
        await draft_service.generate_draft_and_route(request)
    assert "üretilemedi" in str(exc.value)
