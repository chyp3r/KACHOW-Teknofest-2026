"""Structured-output negotiation against Evren's differently-capable models.

`llm-large`/`llm-fast` serve tool calling, so `function_calling` is the
preferred path (see `EvrenClient.generate_structured`). The `guard`
deployment does not: it runs without a tool-call parser and rejects every
`tool_choice` request with a 400. Because every guardrail judge fails open
(`llm_nuance._run_judge` returns None on any error), that rejection was
silent -- PII/leak judging simply never ran on Evren, and nothing said so.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from app.infrastructure.providers.evren import EvrenClient


class _Verdict(BaseModel):
    ok: bool


_TOOL_PARSER_ERROR = (
    'Error code: 400 - litellm.BadRequestError: Hosted_vllmException - '
    '{"error":{"message":"tool_choice=function \\"_Verdict\\" requires '
    '--tool-call-parser to be set","type":"BadRequestError"}}'
)


def _client() -> EvrenClient:
    return EvrenClient(base_url="https://example.invalid/v1", model="guard", api_key="k")


def _patch_invocation(client: EvrenClient, monkeypatch, outcomes: dict[str, Any]) -> list[str]:
    """Record which structured-output method each attempt used."""
    attempts: list[str] = []

    async def _fake(_client, _model, _messages, method):
        attempts.append(method)
        outcome = outcomes[method]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(EvrenClient, "_invoke_structured", staticmethod(_fake))
    monkeypatch.setattr(client, "_build_client", lambda *a, **k: MagicMock())
    return attempts


@pytest.mark.asyncio
async def test_function_calling_is_the_preferred_path(monkeypatch):
    client = _client()
    attempts = _patch_invocation(client, monkeypatch, {"function_calling": _Verdict(ok=True)})

    result = await client.generate_structured([{"role": "user", "content": "x"}], _Verdict)

    assert result == _Verdict(ok=True)
    assert attempts == ["function_calling"]


@pytest.mark.asyncio
async def test_a_model_without_a_tool_call_parser_falls_back_to_json_schema(monkeypatch):
    client = _client()
    attempts = _patch_invocation(
        client,
        monkeypatch,
        {
            "function_calling": Exception(_TOOL_PARSER_ERROR),
            "json_schema": _Verdict(ok=True),
        },
    )

    result = await client.generate_structured([{"role": "user", "content": "x"}], _Verdict)

    assert result == _Verdict(ok=True)
    assert attempts == ["function_calling", "json_schema"]


@pytest.mark.asyncio
async def test_the_fallback_is_learned_once_not_retried_every_call(monkeypatch):
    """Re-probing tool calling on every judge call would spend a doomed
    request per invocation on a model that will never support it."""
    client = _client()
    attempts = _patch_invocation(
        client,
        monkeypatch,
        {
            "function_calling": Exception(_TOOL_PARSER_ERROR),
            "json_schema": _Verdict(ok=True),
        },
    )

    for _ in range(3):
        await client.generate_structured([{"role": "user", "content": "x"}], _Verdict)

    assert attempts == ["function_calling", "json_schema", "json_schema", "json_schema"]


@pytest.mark.asyncio
async def test_an_unrelated_failure_is_raised_rather_than_retried(monkeypatch):
    """Only the tool-call-parser rejection means "this model cannot do tool
    calling". A timeout or an auth error must surface, not silently switch
    the client onto a different code path."""
    client = _client()
    attempts = _patch_invocation(
        client, monkeypatch, {"function_calling": Exception("401 invalid api key")}
    )

    with pytest.raises(Exception, match="401"):
        await client.generate_structured([{"role": "user", "content": "x"}], _Verdict)

    assert attempts == ["function_calling"]
    assert client._structured_method == "function_calling"


@pytest.mark.asyncio
async def test_a_failing_fallback_still_raises(monkeypatch):
    client = _client()
    _patch_invocation(
        client,
        monkeypatch,
        {
            "function_calling": Exception(_TOOL_PARSER_ERROR),
            "json_schema": Exception("guided decoding unavailable"),
        },
    )

    with pytest.raises(Exception, match="guided decoding"):
        await client.generate_structured([{"role": "user", "content": "x"}], _Verdict)
