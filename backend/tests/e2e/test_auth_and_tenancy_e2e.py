"""Login, refresh, logout, and cross-tenant document access -- through real HTTP + RLS.

The one assertion this package proves that none of the 13 existing
MemorySaver graph tests could: two different companies' documents never
cross, through a *real* Postgres RLS policy and a *real* JWT-carried
company_id claim -- not a mocked session that would pass identically against
a completely broken policy (see this package's conftest module docstring).
"""

import pytest

pytestmark = pytest.mark.e2e


async def _login(e2e_client, username: str, password: str) -> dict:
    response = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]


@pytest.mark.asyncio
async def test_refresh_token_issues_a_new_working_access_token(e2e_client, e2e_register_user):
    created = await e2e_register_user()
    tokens = await _login(e2e_client, created["username"], created["password"])

    refreshed = await e2e_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert refreshed.status_code == 200
    new_access_token = refreshed.json()["data"]["access_token"]
    assert new_access_token

    response = await e2e_client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {new_access_token}"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_logout_blacklists_the_access_token(e2e_client, e2e_register_user):
    created = await e2e_register_user()
    tokens = await _login(e2e_client, created["username"], created["password"])
    auth_header = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout_response = await e2e_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=auth_header,
    )
    assert logout_response.status_code == 200

    response_after_logout = await e2e_client.get("/api/v1/documents", headers=auth_header)
    assert response_after_logout.status_code == 401


@pytest.mark.asyncio
async def test_company_a_cannot_read_company_b_s_document(
    e2e_client, e2e_register_user, make_pdf_bytes
):
    company_a = await e2e_register_user()
    company_b = await e2e_register_user()
    tokens_a = await _login(e2e_client, company_a["username"], company_a["password"])
    tokens_b = await _login(e2e_client, company_b["username"], company_b["password"])
    header_a = {"Authorization": f"Bearer {tokens_a['access_token']}"}
    header_b = {"Authorization": f"Bearer {tokens_b['access_token']}"}

    pdf_bytes = make_pdf_bytes(["Şirket A'ya ait gizli bir evrak metni."])
    upload = await e2e_client.post(
        "/api/v1/documents/analyze",
        files={"file": ("a-belgesi.pdf", pdf_bytes, "application/pdf")},
        headers=header_a,
    )
    assert upload.status_code == 200
    storage_path = upload.json()["data"]["storage_path"]

    as_owner = await e2e_client.get(
        f"/api/v1/documents/{storage_path}",
        headers=header_a,
    )
    assert as_owner.status_code == 200

    as_other_company = await e2e_client.get(
        f"/api/v1/documents/{storage_path}",
        headers=header_b,
    )
    assert as_other_company.status_code == 403


@pytest.mark.asyncio
async def test_an_unauthenticated_request_is_rejected_before_reaching_the_handler(e2e_client):
    response = await e2e_client.get("/api/v1/documents")
    assert response.status_code in (401, 403)
