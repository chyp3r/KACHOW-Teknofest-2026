"""Document upload -> analysis -> Q&A indexing, end to end against real Qdrant.

The reason this is an HTTP e2e test and not another mocked unit test: the
3584-vs-768 embedding-dimension mismatch that once silently emptied the
document_qa collection for every upload (see
``DocumentService._index_for_qa``'s own docstring) was only ever visible at
the seam this test exercises -- a real embeddings client, a real Qdrant
collection, and a real probe of the actual vector dimension. A mocked vector
store cannot reproduce a dimension mismatch it was never told to have. This
is also the sentinel for page attribution surviving a future chunk-size
change (Workstream A's ``ChunkingPolicy``): if ``RecursiveChunker`` ever
stops emitting ``start_index``, ``test_indexed_chunks_carry_page_and_
sensitivity_payload`` below is what notices.

The analysis LLM calls are deliberately left unconfigured (``fake_llm``/
``fake_fast_llm`` default to empty/``None`` returns) -- ``document_analysis_
graph``'s own classification node degrades through three fallback tiers to
``document_type=OTHER`` on a structured-output mismatch (see that module's
own except-tier comments), so an upload succeeds and indexes regardless.
That degraded path is exactly what production sees whenever Ollama returns
something the parser can't use, so leaving it unconfigured here is closer to
the real failure mode than hand-crafting a perfect classification would be.
"""

import httpx
import pytest

from app.core.config import settings

pytestmark = pytest.mark.e2e


async def _upload(e2e_client, auth_header: dict, pdf_bytes: bytes, filename: str = "evrak.pdf"):
    return await e2e_client.post(
        "/api/v1/documents/analyze",
        files={"file": (filename, pdf_bytes, "application/pdf")},
        headers=auth_header,
    )


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_upload_returns_a_full_analysis_envelope(
    e2e_client, e2e_register_user, make_pdf_bytes
):
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    header = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    pdf_bytes = make_pdf_bytes(
        [
            "T.C. ÖRNEK BAKANLIĞI\nSayı: 2026/123\nKonu: Görevlendirme\n\n"
            "Personelin 12 Mart 2026 tarihinde göreve başlaması uygundur.",
            "İkinci sayfa: ek bilgiler ve imza bloğu.\ne-imzalıdır",
        ]
    )

    response = await _upload(e2e_client, header, pdf_bytes)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["file_name"] == "evrak.pdf"
    assert data["storage_path"]
    assert data["document_type"]
    assert data["document_type_label"]


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_indexed_chunks_carry_page_and_sensitivity_payload(
    e2e_client, e2e_register_user, make_pdf_bytes
):
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    header = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

    pdf_bytes = make_pdf_bytes(
        [
            "Birinci sayfa metni burada uzunca bir şekilde devam ediyor ki "
            "en az bir chunk üretilsin ve sayfa atfı test edilebilsin.",
            "İkinci sayfa tamamen farklı bir metin içeriyor, ayrı bir chunk "
            "olarak indekslenmesi beklenen bağımsız bir paragraf.",
        ]
    )
    upload = await _upload(e2e_client, header, pdf_bytes)
    assert upload.status_code == 200
    storage_path = upload.json()["data"]["storage_path"]

    async with httpx.AsyncClient(base_url=settings.QDRANT_URL, timeout=10.0) as qdrant:
        scroll = await qdrant.post(
            f"/collections/{e2e_client.e2e_qa_collection}/points/scroll",
            json={
                "limit": 50,
                "with_payload": True,
                "filter": {"must": [{"key": "storage_path", "match": {"value": storage_path}}]},
            },
        )

    assert scroll.status_code == 200
    points = scroll.json()["result"]["points"]
    assert len(points) > 0, "upload produced no document_qa chunks"
    for point in points:
        payload = point["payload"]
        assert payload["storage_path"] == storage_path
        assert "sensitivity_rank" in payload
        assert "sensitivity_level" in payload
        assert "page" in payload
        assert isinstance(payload["page"], int)


async def _qa_chunk_count(e2e_client, storage_path: str) -> int:
    async with httpx.AsyncClient(base_url=settings.QDRANT_URL, timeout=10.0) as qdrant:
        scroll = await qdrant.post(
            f"/collections/{e2e_client.e2e_qa_collection}/points/scroll",
            json={
                "limit": 200,
                "with_payload": False,
                "filter": {"must": [{"key": "storage_path", "match": {"value": storage_path}}]},
            },
        )
    return len(scroll.json()["result"]["points"])


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_correcting_document_text_reindexes_without_duplicating_chunks(
    e2e_client, e2e_register_user, make_pdf_bytes
):
    """Idempotency guarantee documented on ``_index_for_qa`` itself.

    Uses ``PUT .../text`` (hand-corrected OCR text), not ``POST .../
    re-extract`` -- the latter always calls the real vision model directly
    (``OllamaVisionExtractor``, bypassing ``get_llm_client``/
    ``get_fast_llm_client`` entirely), which this fixture does not fake and
    which genuinely has no Ollama to reach here. ``update_document_text`` is
    the one re-derivation path that is deterministic and model-free by
    design (see that route's own docstring), so it is also the one that
    proves ``_index_for_qa``'s re-indexing without depending on a live model.
    """
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    header = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
    pdf_bytes = make_pdf_bytes(["Tekrarlı yükleme testinin metni, ilk hali."])

    first = await _upload(e2e_client, header, pdf_bytes, filename="tekrar.pdf")
    assert first.status_code == 200
    storage_path = first.json()["data"]["storage_path"]
    first_count = await _qa_chunk_count(e2e_client, storage_path)
    assert first_count > 0

    corrected = await e2e_client.put(
        f"/api/v1/documents/{storage_path}/text",
        json={"pages": ["Tekrarlı yükleme testinin düzeltilmiş metni, ikinci hali."]},
        headers=header,
    )
    assert corrected.status_code == 200

    second_count = await _qa_chunk_count(e2e_client, storage_path)
    assert second_count > 0
    assert second_count == first_count
