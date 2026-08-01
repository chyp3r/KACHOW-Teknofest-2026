"""API tests for the standalone unit-routing suggestion endpoint.

Deliberately independent of POST /documents/draft: a human who edits a draft
after it was generated should get a fresh routing decision without paying for
a new generation.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependency import get_routing_graph
from app.main import app

ENDPOINT = "/api/v1/routing/suggest"

client = TestClient(app, raise_server_exceptions=False)


def _override(graph):
    app.dependency_overrides[get_routing_graph] = lambda: graph


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_suggest_routing_returns_the_graph_decision():
    graph = AsyncMock()
    graph.ainvoke.return_value = {
        "routed_unit": "İnsan Kaynakları Daire Başkanlığı",
        "priority": "Normal",
        "reasoning": "Personel izin talebiyle ilgili.",
        "justification": "Personel izin talebiyle ilgili.",
    }
    _override(graph)

    response = client.post(
        ENDPOINT, json={"draft": "Sayın Makam, izin talebimi arz ederim.", "confidence_score": 90.0}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["routed_unit"] == "İnsan Kaynakları Daire Başkanlığı"
    assert body["data"]["priority"] == "Normal"


def test_suggest_routing_passes_the_draft_and_score_to_the_graph():
    graph = AsyncMock()
    graph.ainvoke.return_value = {"routed_unit": "X", "priority": "Yüksek", "reasoning": "r"}
    _override(graph)

    client.post(ENDPOINT, json={"draft": "Bir taslak metni.", "confidence_score": 55.5})

    invoke_args = graph.ainvoke.await_args.args[0]
    assert invoke_args["draft"] == "Bir taslak metni."
    assert invoke_args["confidence_score"] == 55.5


def test_suggest_routing_defaults_confidence_score_to_100():
    graph = AsyncMock()
    graph.ainvoke.return_value = {"routed_unit": "X", "priority": "Normal", "reasoning": "r"}
    _override(graph)

    response = client.post(ENDPOINT, json={"draft": "Kısa bir taslak."})

    assert response.status_code == 200
    invoke_args = graph.ainvoke.await_args.args[0]
    assert invoke_args["confidence_score"] == 100.0


def test_suggest_routing_rejects_an_empty_draft():
    graph = AsyncMock()
    _override(graph)

    response = client.post(ENDPOINT, json={"draft": ""})

    assert response.status_code == 422
    graph.ainvoke.assert_not_called()


def test_suggest_routing_maps_a_graph_failure_to_502():
    graph = AsyncMock()
    graph.ainvoke.side_effect = RuntimeError("model unavailable")
    _override(graph)

    response = client.post(ENDPOINT, json={"draft": "Bir taslak metni."})

    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AI_EXECUTION_ERROR"


def test_suggest_routing_falls_back_to_human_approval_label_when_the_graph_omits_it():
    graph = AsyncMock()
    graph.ainvoke.return_value = {}
    _override(graph)

    response = client.post(ENDPOINT, json={"draft": "Bir taslak metni."})

    assert response.status_code == 200
    assert response.json()["data"]["routed_unit"] == "İnsan Onayı Gerekli"
