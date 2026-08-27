"""`app.observability.prometheus_query` -- global token kullanım paneli için
küçük, hataya dayanıklı Prometheus istemcisi."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.observability.prometheus_query import llm_token_usage


def _prom_response(pairs: list[tuple[dict, str]]) -> dict:
    return {
        "status": "success",
        "data": {
            "result": [{"metric": metric, "value": [0, value]} for metric, value in pairs]
        },
    }


@pytest.mark.asyncio
async def test_it_sums_token_series_by_agent_and_kind():
    by_agent = _prom_response([({"agent": "writer"}, "1000"), ({"agent": "judge"}, "250")])
    by_kind = _prom_response([({"kind": "input"}, "800"), ({"kind": "output"}, "450")])

    async def _fake_get(url, params=None):
        promql = params["query"]
        body = by_agent if "agent" in promql else by_kind
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(side_effect=_fake_get)
        result = await llm_token_usage()

    assert result["by_agent"] == {"writer": 1000.0, "judge": 250.0}
    assert result["by_kind"] == {"input": 800.0, "output": 450.0}
    assert result["total"] == 1250.0
    assert result["available"] is True


@pytest.mark.asyncio
async def test_an_unreachable_prometheus_is_an_empty_panel_not_an_error():
    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            side_effect=httpx.ConnectError("no route to host")
        )
        result = await llm_token_usage()

    assert result == {"by_agent": {}, "by_kind": {}, "total": 0, "available": False}
