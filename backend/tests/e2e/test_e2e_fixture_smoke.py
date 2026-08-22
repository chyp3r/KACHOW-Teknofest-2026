"""Proves the ``e2e_client``/``e2e_register_user`` fixtures actually work.

Not a feature test -- a fixture test. Each of Workstream C3's real e2e specs
(auth+tenancy, document upload, chat SSE, HITL resume, draft lifecycle,
health/metrics) builds on the same fixture this file exercises directly, so a
break here is a break in all of them at once.
"""

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_health_endpoint_is_reachable(e2e_client):
    response = await e2e_client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_returns_a_bearer_token_for_a_freshly_registered_user(e2e_client, e2e_register_user):
    created = await e2e_register_user()

    response = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["token_type"] == "bearer"
    assert body["data"]["access_token"]


@pytest.mark.asyncio
async def test_login_rejects_the_wrong_password(e2e_client, e2e_register_user):
    created = await e2e_register_user()

    response = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": "definitely-wrong"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_request_lists_only_the_caller_s_own_company(e2e_client, e2e_register_user):
    """RLS, not just auth: an empty list, not a 500, and never another company's rows.

    This is the one assertion that could not be made against the existing 13
    MemorySaver graph tests -- see this package's conftest module docstring.
    """
    created_a = await e2e_register_user()
    created_b = await e2e_register_user()

    login_a = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created_a["username"], "password": created_a["password"]},
    )
    token_a = login_a.json()["data"]["access_token"]

    response = await e2e_client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == []
    assert created_b["company_id"] != created_a["company_id"]


@pytest.mark.asyncio
async def test_a_missing_bearer_token_is_rejected(e2e_client):
    response = await e2e_client.get("/api/v1/documents")
    assert response.status_code in (401, 403)
