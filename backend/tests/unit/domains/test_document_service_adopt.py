"""Unit tests for `DocumentService.adopt_pool_item` (Faz 5, #205) --
copy-on-write for a transferred document's own pool item."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.exceptions.authorization import AuthorizationException
from app.api.exceptions.not_found import NotFoundException
from app.api.exceptions.validation import ValidationException
from app.core.config import settings
from app.domains.documents.model.document_model import DocumentModel
from app.domains.documents.service import DocumentService, _analysis_cache_key
from app.domains.pools.model.document_pool_item_model import DocumentPoolItemModel
from app.domains.pools.model.document_pool_model import DocumentPoolModel
from app.domains.users.model.user_model import UserModel
from app.infrastructure.extractors.base import BaseDocumentExtractor
from app.infrastructure.storage.base import BaseStorage


def _user(**overrides) -> UserModel:
    fields = dict(
        id="emp-2", company_id="company-1", username="emp2", email="emp2@example.com",
        role="employee", clearance_level="hizmete_ozel", is_active=True, is_deleted=False,
        hashed_password="x", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    )
    fields.update(overrides)
    return UserModel(**fields)


def _pool(**overrides) -> DocumentPoolModel:
    fields = dict(
        id="pool-1", company_id="company-1", owner_type="user", owner_id="emp-2",
        name="Kişisel Havuz", is_default=True,
    )
    fields.update(overrides)
    return DocumentPoolModel(**fields)


def _item(**overrides) -> DocumentPoolItemModel:
    fields = dict(
        id="item-1", company_id="company-1", pool_id="pool-1", document_id="uploads/sender.pdf",
        added_by="emp-1", source="transfer", transferred_by="emp-1",
        metadata_snapshot={
            "document_type": "official_letter",
            "document_type_label": "Resmî Yazı",
            "compliance_status": "compliant",
            "summary": "Özet.",
            "sensitivity_level": "hizmete_ozel",
            "pii_flagged": False,
        },
    )
    fields.update(overrides)
    return DocumentPoolItemModel(**fields)


def _source_document(**overrides) -> DocumentModel:
    fields = dict(
        id="uploads/sender.pdf", company_id="company-1", owner_id="emp-1", file_name="evrak.pdf",
        document_type="official_letter", document_type_label="Resmî Yazı",
        compliance_status="compliant", summary="Özet.", sensitivity_level="hizmete_ozel",
        pii_flagged=False,
    )
    fields.update(overrides)
    return DocumentModel(**fields)


def _build_service(*, pool_item_repository=None, pool_repository=None, document_repository=None,
                    quota_service=None):
    # A stateful fake, not a bare AsyncMock -- adopt_pool_item's cache copy
    # (_copy_analysis_cache) now reads/writes through self.storage exactly
    # like the blob does (see app.domains.documents.service.
    # _analysis_cache_key), so get_file/put_file must actually distinguish
    # the blob key from the cache key instead of returning one fixed value
    # for every call.
    blobs: dict[str, bytes] = {"uploads/sender.pdf": b"%PDF-1.7 fake bytes"}

    async def _put_file(file_path: str, content: bytes) -> str:
        blobs[file_path] = content
        return "uploads/adopted.pdf"

    async def _get_file(file_path: str) -> bytes:
        if file_path not in blobs:
            raise FileNotFoundError(file_path)
        return blobs[file_path]

    async def _delete_file(file_path: str) -> bool:
        return blobs.pop(file_path, None) is not None

    storage = AsyncMock(spec=BaseStorage)
    storage.put_file.side_effect = _put_file
    storage.get_file.side_effect = _get_file
    storage.delete_file.side_effect = _delete_file
    storage.blobs = blobs

    extractor = AsyncMock(spec=BaseDocumentExtractor)
    analysis_graph = MagicMock()

    service = DocumentService(
        storage=storage,
        extractor=extractor,
        analysis_graph=analysis_graph,
        document_repository=document_repository if document_repository is not None else AsyncMock(),
        pool_repository=pool_repository if pool_repository is not None else AsyncMock(),
        pool_item_repository=pool_item_repository if pool_item_repository is not None else AsyncMock(),
        quota_service=quota_service,
    )
    return service, storage


# ---------- authorization ----------


async def test_raises_not_found_when_item_missing():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = None
    service, _ = _build_service(pool_item_repository=pool_item_repository)

    with pytest.raises(NotFoundException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")


async def test_raises_authorization_error_when_caller_is_not_the_pool_s_own_owner():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool(owner_id="someone-else")
    service, _ = _build_service(pool_item_repository=pool_item_repository, pool_repository=pool_repository)

    with pytest.raises(AuthorizationException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(id="emp-2"), company_id="company-1")


async def test_admin_still_cannot_adopt_someone_else_s_pool_item():
    """No Admin/Manager bypass here -- adopting creates a personal copy for
    the caller specifically, unlike most of this module's authorization."""
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool(owner_id="emp-2")
    service, _ = _build_service(pool_item_repository=pool_item_repository, pool_repository=pool_repository)

    with pytest.raises(AuthorizationException):
        await service.adopt_pool_item(
            item_id="item-1", current_user=_user(id="admin-1", role="admin"), company_id="company-1"
        )


async def test_raises_not_found_when_pool_missing():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = None
    service, _ = _build_service(pool_item_repository=pool_item_repository, pool_repository=pool_repository)

    with pytest.raises(AuthorizationException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")


# ---------- validation ----------


async def test_rejects_a_non_transfer_item():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item(source="upload", metadata_snapshot=None)
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    service, _ = _build_service(pool_item_repository=pool_item_repository, pool_repository=pool_repository)

    with pytest.raises(ValidationException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")


async def test_raises_not_found_when_source_document_missing():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = None
    service, _ = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )

    with pytest.raises(NotFoundException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")


async def test_wraps_a_storage_read_failure_as_a_validation_error():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    service, storage = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )
    storage.get_file.side_effect = RuntimeError("blob gone")

    with pytest.raises(ValidationException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")
    document_repository.create.assert_not_awaited()


async def test_raises_validation_error_when_repositories_are_not_wired():
    storage = AsyncMock(spec=BaseStorage)
    extractor = AsyncMock(spec=BaseDocumentExtractor)
    service = DocumentService(storage=storage, extractor=extractor, analysis_graph=MagicMock())

    with pytest.raises(ValidationException):
        await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")


# ---------- happy path ----------


async def test_copies_the_blob_under_a_new_storage_key():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    service, storage = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )

    await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")

    # Also probes the analysis cache key (_analysis_cache_key) and finds
    # nothing there -- no cache was seeded for this test -- so put_file is
    # only called once, for the blob itself.
    storage.get_file.assert_any_await("uploads/sender.pdf")
    storage.put_file.assert_awaited_once()
    assert storage.put_file.await_args.args[1] == b"%PDF-1.7 fake bytes"


async def test_registers_a_new_document_owned_by_the_caller_from_the_snapshot():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document(
        # The live sender-side row has since drifted -- the snapshot frozen
        # at transfer time is what the recipient actually saw and should win.
        summary="Değişmiş özet.",
    )
    service, _ = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )

    await service.adopt_pool_item(item_id="item-1", current_user=_user(id="emp-2"), company_id="company-1")

    document_repository.create.assert_awaited_once()
    new_document = document_repository.create.await_args.args[0]
    assert new_document.id == "uploads/adopted.pdf"
    assert new_document.owner_id == "emp-2"
    assert new_document.company_id == "company-1"
    assert new_document.summary == "Özet."  # from the snapshot, not the live row
    assert new_document.sensitivity_level == "hizmete_ozel"


async def test_repoints_the_pool_item_at_the_new_document_and_clears_the_snapshot():
    pool_item_repository = AsyncMock()
    item = _item()
    pool_item_repository.get_by_id.return_value = item
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    service, _ = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )

    result = await service.adopt_pool_item(
        item_id="item-1", current_user=_user(id="emp-2"), company_id="company-1"
    )

    assert result is item
    assert item.document_id == "uploads/adopted.pdf"
    assert item.source == "adopted"
    assert item.metadata_snapshot is None
    assert item.transferred_by == "emp-1"  # provenance survives adoption
    pool_item_repository.save.assert_awaited_once_with(item)


async def test_increments_the_document_quota_when_a_quota_service_is_configured():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    quota_service = AsyncMock()
    service, _ = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
        quota_service=quota_service,
    )

    await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")

    quota_service.check_and_increment.assert_awaited_once()


# ---------- analysis cache + reindexing ----------


async def test_copies_the_analysis_cache_under_the_new_storage_key():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    service, storage = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )
    service._index_for_qa = AsyncMock()

    cache_payload = {"extracted_text": "İçerik.", "pages": ["İçerik."], "analysis": {"summary": "Özet."}}
    storage.blobs[_analysis_cache_key("uploads/sender.pdf")] = json.dumps(
        cache_payload, ensure_ascii=False
    ).encode("utf-8")

    await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")

    new_cache = json.loads(storage.blobs[_analysis_cache_key("uploads/adopted.pdf")])
    assert new_cache == cache_payload
    service._index_for_qa.assert_awaited_once()
    call_args = service._index_for_qa.await_args
    assert call_args.args[0] == "uploads/adopted.pdf"
    assert call_args.args[1] == "İçerik."


async def test_skips_reindexing_when_the_source_has_no_cache():
    pool_item_repository = AsyncMock()
    pool_item_repository.get_by_id.return_value = _item()
    pool_repository = AsyncMock()
    pool_repository.get_by_id.return_value = _pool()
    document_repository = AsyncMock()
    document_repository.get_by_id.return_value = _source_document()
    service, _ = _build_service(
        pool_item_repository=pool_item_repository,
        pool_repository=pool_repository,
        document_repository=document_repository,
    )
    service._index_for_qa = AsyncMock()

    result = await service.adopt_pool_item(item_id="item-1", current_user=_user(), company_id="company-1")

    assert result.source == "adopted"
    service._index_for_qa.assert_not_awaited()
