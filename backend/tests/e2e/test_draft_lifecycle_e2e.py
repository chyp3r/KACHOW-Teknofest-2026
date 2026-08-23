"""Draft generation via the direct ``POST /documents/draft`` endpoint, over real HTTP.

Deliberately not the chat path: per this package's own research, drafting
through chat is the only path with interrupt/resume semantics (see
``test_chat_hitl_resume_e2e.py``), while this direct endpoint always returns
synchronously -- a draft with unfilled placeholders comes back with
``missing_information`` populated rather than pausing (see
``DraftService.generate_draft_and_route``'s own behavior). Both paths are
worth covering; this one is the simpler, faster one.

The writer/reviser call ``client.stream(...)``, not ``generate_structured``
(see ``app/ai/workflows/draft_graph.py``), so the deterministic lever here is
``fake_llm.stream_chunks`` -- the concatenation of those chunks becomes the
draft text verbatim. The judge (``JudgeAgent.generate_structured``) is left
unconfigured on purpose: ``judge_draft`` never raises and degrades to
``verdict=None`` on any schema mismatch (see that function's own docstring),
which is exactly what an unconfigured fake produces -- the same degraded
path production takes whenever the fast-tier model returns something the
judge's schema can't parse.
"""

import pytest

pytestmark = pytest.mark.e2e


async def _authed_header(e2e_client, e2e_register_user) -> dict:
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


async def _upload_and_classify(e2e_client, header: dict, make_pdf_bytes) -> dict:
    pdf_bytes = make_pdf_bytes(
        ["T.C. ÖRNEK BAKANLIĞI\nSayı: 2026/456\nKonu: Bilgi talebi.\n\nGereğinin yapılması rica olunur."]
    )
    upload = await e2e_client.post(
        "/api/v1/documents/analyze",
        files={"file": ("talep.pdf", pdf_bytes, "application/pdf")},
        headers=header,
    )
    assert upload.status_code == 200
    data = upload.json()["data"]
    return {
        "storage_path": data["storage_path"],
        "classification": {
            "document_type": data["document_type"],
            "document_type_label": data["document_type_label"],
            "summary": data["summary"],
            "fields": data["fields"],
            "missing_fields": data["missing_fields"],
            "mevzuat_references": data["mevzuat_references"],
        },
    }


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_a_complete_draft_is_returned_ready_to_route(
    e2e_client, e2e_register_user, make_pdf_bytes, fake_llm
):
    header = await _authed_header(e2e_client, e2e_register_user)
    uploaded = await _upload_and_classify(e2e_client, header, make_pdf_bytes)
    fake_llm.stream_chunks = [
        "Sayın İlgili,\n\n",
        "Talebiniz incelenmiş olup gereği yapılacaktır.\n\n",
        "Saygılarımızla.",
    ]

    response = await e2e_client.post(
        "/api/v1/documents/draft",
        json={
            "storage_path": uploaded["storage_path"],
            "classification": uploaded["classification"],
            "instructions": "Kısa ve resmi bir yanıt yazın.",
        },
        headers=header,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert "Talebiniz" in data["draft"]
    assert data["missing_information"] == []
    assert isinstance(data["confidence_score"], (int, float))


@pytest.mark.timeout(120)
@pytest.mark.asyncio
async def test_a_draft_with_an_unfilled_placeholder_reports_missing_information(
    e2e_client, e2e_register_user, make_pdf_bytes, fake_llm
):
    header = await _authed_header(e2e_client, e2e_register_user)
    uploaded = await _upload_and_classify(e2e_client, header, make_pdf_bytes)
    fake_llm.stream_chunks = [
        "Sayın [ALICI BİLGİSİ],\n\n",
        "Talebiniz değerlendirilmektedir.\n\n",
        "Saygılarımızla.",
    ]

    response = await e2e_client.post(
        "/api/v1/documents/draft",
        json={
            "storage_path": uploaded["storage_path"],
            "classification": uploaded["classification"],
            "instructions": "",
        },
        headers=header,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["missing_information"]) > 0
    assert "[" in data["draft"]


@pytest.mark.asyncio
async def test_drafting_against_another_company_s_document_is_forbidden(
    e2e_client, e2e_register_user, make_pdf_bytes
):
    header_a = await _authed_header(e2e_client, e2e_register_user)
    header_b = await _authed_header(e2e_client, e2e_register_user)
    uploaded = await _upload_and_classify(e2e_client, header_a, make_pdf_bytes)

    response = await e2e_client.post(
        "/api/v1/documents/draft",
        json={
            "storage_path": uploaded["storage_path"],
            "classification": uploaded["classification"],
            "instructions": "",
        },
        headers=header_b,
    )

    assert response.status_code == 403
