from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.transfer.slots import TransferSlots, extract_transfer_slots


@pytest.fixture
def mock_llm_client():
    client = MagicMock()
    client.count_tokens = MagicMock(return_value=1)
    return client


@pytest.mark.asyncio
async def test_extracts_recipient_and_artifact_kind(mock_llm_client):
    mock_llm_client.generate_structured = AsyncMock(
        return_value=TransferSlots(recipient_name="Ahmet", artifact_kind="draft", artifact_reference=None)
    )
    slots = await extract_transfer_slots(mock_llm_client, "Son taslağı Ahmet'e gönder")
    assert slots.recipient_name == "Ahmet"
    assert slots.artifact_kind == "draft"


@pytest.mark.asyncio
async def test_a_failed_call_degrades_to_empty_slots_not_an_exception(mock_llm_client):
    """The only LLM call in the whole transfer flow -- a failure here must
    never propagate. It just means the deterministic resolution ladder gets
    nothing to narrow with (see ArtifactResolutionService/
    RecipientResolutionService), not that the turn breaks."""
    mock_llm_client.generate_structured = AsyncMock(side_effect=RuntimeError("provider down"))
    slots = await extract_transfer_slots(mock_llm_client, "Son taslağı gönder")
    assert slots == TransferSlots()
    assert slots.recipient_name is None
    assert slots.artifact_kind is None


@pytest.mark.asyncio
async def test_a_message_naming_nobody_extracts_no_recipient(mock_llm_client):
    mock_llm_client.generate_structured = AsyncMock(
        return_value=TransferSlots(recipient_name=None, artifact_kind="draft", artifact_reference=None)
    )
    slots = await extract_transfer_slots(mock_llm_client, "Son taslağı gönder")
    assert slots.recipient_name is None
