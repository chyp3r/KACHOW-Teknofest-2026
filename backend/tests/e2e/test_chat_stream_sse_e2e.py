"""POST /api/v1/chat/stream over real HTTP: the SSE wire contract.

Parses actual ``text/event-stream`` bytes off ``httpx.AsyncClient.stream``
(over ``ASGITransport``, which still streams a real ``StreamingResponse``
chunk by chunk -- see this package's own conftest docstring), rather than
asserting against ``chat_service`` internals directly. What this proves that
a unit test on ``ChatService`` cannot: the literal `"data: ...\\n\\n"` framing
`_sse_response` writes to the wire, and the terminal `"data: [DONE]\\n\\n"`
line, survive real ASGI response streaming.

Deliberately not asserting a specific reply or intent classification --
which node the planning graph's intent ladder resolves to is exactly what
the (extensive, mocked) unit test suite already covers, and pinning it here
would make this suite fail on an unrelated routing tweak. The contract this
suite owns is: `session` is always first, `[DONE]` is always last, and the
stream always reaches *a* terminal event (`final_result`, `interrupt`, or
`error`) in between -- never a bare disconnect.
"""

import json

import pytest

pytestmark = pytest.mark.e2e


async def _stream_events(e2e_client, header: dict, body: dict) -> list[dict]:
    events: list[dict] = []
    async with e2e_client.stream(
        "POST", "/api/v1/chat/stream", json=body, headers=header
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[len("data: "):]
            if raw == "[DONE]":
                events.append({"event": "__done__"})
                break
            events.append(json.loads(raw))
    return events


async def _authed_header(e2e_client, e2e_register_user) -> dict:
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_a_chat_turn_always_starts_with_session_and_ends_with_done(
    e2e_client, e2e_register_user
):
    header = await _authed_header(e2e_client, e2e_register_user)

    events = await _stream_events(
        e2e_client, header, {"message": "Merhaba, nasıl yardımcı olabilirsin?"}
    )

    assert events[0]["event"] == "session"
    assert events[0]["thread_id"]
    assert events[-1]["event"] == "__done__"
    terminal_kinds = {"final_result", "interrupt", "error"}
    assert any(e.get("event") in terminal_kinds for e in events[1:-1]), (
        f"no terminal event before [DONE]: {[e.get('event') for e in events]}"
    )


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_every_thread_id_is_scoped_to_the_authenticated_user(
    e2e_client, e2e_register_user
):
    header = await _authed_header(e2e_client, e2e_register_user)

    events = await _stream_events(e2e_client, header, {"message": "Merhaba"})

    thread_id = events[0]["thread_id"]
    assert ":" in thread_id


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_an_invalid_session_id_is_rejected_before_streaming_starts(
    e2e_client, e2e_register_user
):
    header = await _authed_header(e2e_client, e2e_register_user)

    response = await e2e_client.post(
        "/api/v1/chat/stream",
        json={"message": "Merhaba", "session_id": "has spaces, invalid"},
        headers=header,
    )

    assert response.status_code == 422
