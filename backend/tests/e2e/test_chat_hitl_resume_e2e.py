"""Chat-driven drafting pauses on real gates, then resumes -- over real HTTP + a real checkpointer.

A drafting turn can pause at two distinct gates, and possibly more than once
at the first of them -- discovered empirically running this test against the
real graph (an earlier draft assumed exactly one pause each and failed
against real behavior):

1. ``brief_gate_node`` (``kind="writing_brief"``) -- always runs first,
   before ``draft_result`` is produced at all, and re-pauses (a new round)
   for any of its required slots (subject line, number line, date, closing
   formula, signature block) a prior round's answers didn't resolve, since a
   single flat placeholder value can satisfy some slots and not others.
2. ``human_gate_node`` (``kind="missing_information"``) -- only reached once
   the brief is resolved and the writer has actually produced a draft
   containing a ``[...]``-style bracket placeholder (``PLACEHOLDER_PATTERN``,
   ``app/ai/verification/draft_verifier.py``). A low-scoring but *complete*
   draft (``NEEDS_HUMAN_APPROVAL``) ships without pausing here -- that status
   is not exercised by this test.

This test drives the resume loop generically -- answer whatever questions
the current pause asks, resume, repeat -- rather than hard-coding an exact
pause count, since the number of ``writing_brief`` rounds is an internal
implementation detail this suite should not need to track. It still asserts
that a genuine ``missing_information`` pause was reached at least once,
which is the property this file exists to prove.

The ``draft`` intent itself is reached deterministically via keyword rules
(``app/ai/workflows/intent_rules.py``'s ``DRAFT_RULES``, e.g. "taslak") -- no
LLM call needed for routing, confirmed by this test's own run log ("Plan
resolved via fused: intent=draft").

The one thing this suite needs that a unit test on ``ChatService`` cannot
prove: several separate HTTP requests (the initial stream, then each resume)
sharing a checkpoint through a *real* Postgres-backed LangGraph checkpointer
(``app.infrastructure.checkpointing.postgres``) -- not the ``MemorySaver``
the 13 pre-existing "end-to-end" tests use, which never leaves process
memory and therefore never proves separate requests actually agree on state.
"""

import json

import pytest

pytestmark = pytest.mark.e2e

#: Generous, but bounded -- a real bug that made the gate loop forever
#: (residual answers never actually resolving) should fail loudly, not hang
#: the suite.
_MAX_RESUME_ROUNDS = 8


async def _authed_header(e2e_client, e2e_register_user) -> dict:
    created = await e2e_register_user()
    login = await e2e_client.post(
        "/api/v1/auth/login",
        json={"username": created["username"], "password": created["password"]},
    )
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


async def _upload(e2e_client, header: dict, make_pdf_bytes) -> str:
    pdf_bytes = make_pdf_bytes(
        ["T.C. ÖRNEK BAKANLIĞI\nSayı: 2026/789\nKonu: Bilgi talebi.\n\nGereğinin yapılması rica olunur."]
    )
    upload = await e2e_client.post(
        "/api/v1/documents/analyze",
        files={"file": ("hitl-talep.pdf", pdf_bytes, "application/pdf")},
        headers=header,
    )
    assert upload.status_code == 200
    return upload.json()["data"]["storage_path"]


async def _stream_events(e2e_client, header: dict, path: str, body: dict) -> list[dict]:
    events: list[dict] = []
    async with e2e_client.stream("POST", path, json=body, headers=header) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[len("data: "):]
            if raw == "[DONE]":
                events.append({"event": "__done__"})
                break
            events.append(json.loads(raw))
    return events


async def _drive_to_completion(
    e2e_client, header: dict, session_id: str, turn_events: list[dict]
) -> tuple[list[dict], set[str]]:
    """Answer every interrupt generically and resume until a terminal event.

    A resumed node replays from its own top before ``interrupt()`` returns
    the answer (see ``brief_gate_node``'s own comment on why -- ``interrupt()``
    re-executes everything above it on resume), so a *successful* resume's
    event stream still contains one ``interrupt`` SSE event: a replay echo
    of the just-answered pause, emitted before the node proceeds past it.
    Only the *last* interrupt in a turn reflects where the run actually
    stopped -- an earlier one in the same turn is that echo, not a second
    genuine pause.

    Returns ``(final_turn_events, interrupt_kinds_seen)``.
    """
    interrupt_kinds: set[str] = set()
    for _ in range(_MAX_RESUME_ROUNDS):
        interrupts = [e for e in turn_events if e.get("event") == "interrupt"]
        current_interrupt = interrupts[-1] if interrupts else None
        has_final = any(e.get("event") == "final_result" for e in turn_events)
        if current_interrupt is None or has_final:
            return turn_events, interrupt_kinds
        interrupt_kinds.add(current_interrupt["kind"])
        answers = {
            q["key"]: "Ankara Valiliği" for q in current_interrupt["payload"]["questions"]
        }
        turn_events = await _stream_events(
            e2e_client,
            header,
            "/api/v1/chat/resume",
            {"session_id": session_id, "action": "answer", "answers": answers},
        )
    raise AssertionError(f"still pausing after {_MAX_RESUME_ROUNDS} resume rounds")


@pytest.mark.timeout(90)
@pytest.mark.asyncio
async def test_a_draft_with_an_unfilled_placeholder_pauses_then_resume_completes_it(
    e2e_client, e2e_register_user, make_pdf_bytes, fake_llm
):
    header = await _authed_header(e2e_client, e2e_register_user)
    storage_path = await _upload(e2e_client, header, make_pdf_bytes)
    fake_llm.stream_chunks = [
        "Sayın [ALICI BİLGİSİ],\n\n",
        "Talebiniz değerlendirilmiş olup gereği yapılacaktır.\n\n",
        "Saygılarımızla.",
    ]

    first_turn = await _stream_events(
        e2e_client,
        header,
        "/api/v1/chat/stream",
        {"message": "Bu evrak için resmi bir yazı taslağı hazırla.", "document_id": storage_path},
    )
    assert first_turn[0]["event"] == "session"
    session_id = first_turn[0]["thread_id"]

    final_turn, interrupt_kinds = await _drive_to_completion(
        e2e_client, header, session_id, first_turn
    )

    assert "writing_brief" in interrupt_kinds
    assert "missing_information" in interrupt_kinds
    assert final_turn[-1]["event"] == "__done__"
    final_events = [e for e in final_turn if e.get("event") == "final_result"]
    assert len(final_events) == 1
    assert "[ALICI BİLGİSİ]" not in final_events[0]["reply"]


@pytest.mark.timeout(60)
@pytest.mark.asyncio
async def test_resume_on_a_session_owned_by_another_user_is_forbidden(
    e2e_client, e2e_register_user, make_pdf_bytes, fake_llm
):
    header_a = await _authed_header(e2e_client, e2e_register_user)
    header_b = await _authed_header(e2e_client, e2e_register_user)
    storage_path = await _upload(e2e_client, header_a, make_pdf_bytes)
    fake_llm.stream_chunks = ["Sayın [ALICI],\n\nMetin.\n\nSaygılarımızla."]

    first_turn = await _stream_events(
        e2e_client,
        header_a,
        "/api/v1/chat/stream",
        {"message": "Bu evrak için taslak hazırla.", "document_id": storage_path},
    )
    thread_id = first_turn[0]["thread_id"]

    response = await e2e_client.post(
        "/api/v1/chat/resume",
        json={"session_id": thread_id, "action": "answer", "answers": {}},
        headers=header_b,
    )

    assert response.status_code == 403
