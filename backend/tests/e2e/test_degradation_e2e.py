"""Proves a documented degrade path for real, over the full HTTP+RLS+real-
Qdrant stack -- not the sub-graphs' own unit tests, which already cover
``retrieve_source_chunks``/``retrieve_examples``/``PrototypeMatcher``/the
rate limiter degrading in isolation (see ``backend/tests/unit/ai/
test_draft_source_chunks.py``, ``test_example_retriever.py``,
``test_prototype_matcher.py``, ``backend/tests/unit/api/test_rate_limit.py``).

The one degrade path in ``DocumentService._index_for_qa``'s own docstring
("a bug in a hint-gatherer must never be able to leave ... empty") that had
no test anywhere before this file: a Qdrant outage during indexing must
never fail the document *upload* itself, only the search index that upload
would otherwise have populated. `_index_for_qa`'s own broad
``except Exception: logger.exception(...)`` at the end of its indexing try
block is what this test is actually watching -- everything above it
(``delete_by_filter``, ``create_collection``, ``upsert_documents``) is
monkeypatched on the real ``QdrantStore`` class to simulate an unreachable
cluster, real HTTP round trip and real RLS otherwise untouched.
"""

from unittest.mock import AsyncMock

import pytest

from app.infrastructure.vectorstore.qdrant import QdrantStore

pytestmark = pytest.mark.e2e


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_a_qdrant_outage_during_indexing_does_not_fail_the_upload(
    e2e_client, e2e_register_user, make_pdf_bytes, monkeypatch
):
    # Simulates the whole cluster being unreachable for the one write path
    # a plain document upload actually touches (_index_for_qa) -- not a
    # partial/single-method failure, so this cannot pass by accident because
    # some other call happened to still succeed.
    outage = AsyncMock(side_effect=RuntimeError("qdrant unreachable"))
    monkeypatch.setattr(QdrantStore, "delete_by_filter", outage)
    monkeypatch.setattr(QdrantStore, "create_collection", outage)
    monkeypatch.setattr(QdrantStore, "upsert_documents", outage)

    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    header = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    pdf_bytes = make_pdf_bytes(
        [
            "T.C. ÖRNEK BAKANLIĞI\nSayı: 2026/456\nKonu: Test\n\n"
            "Qdrant kapalıyken bile bu yükleme başarılı olmalıdır."
        ]
    )

    response = await e2e_client.post(
        "/api/v1/documents/analyze",
        files={"file": ("evrak.pdf", pdf_bytes, "application/pdf")},
        headers=header,
    )

    # The upload itself -- storage write, DB row, LLM-backed classification
    # -- must succeed regardless: none of it depends on the QA index.
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["storage_path"]
    assert data["document_type"]

    # And the document is otherwise fully usable afterwards -- the outage
    # degraded exactly one thing (the search index _index_for_qa would have
    # populated), not the document record or its cached analysis.
    fetch = await e2e_client.get(f"/api/v1/documents/{data['storage_path']}", headers=header)
    assert fetch.status_code == 200
