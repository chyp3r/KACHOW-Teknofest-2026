"""End-to-end proof of the two Faz 7 assist -> draft/revise handoff paths.

Exercises the real compiled planning graph, same division of concerns
`test_hitl_flow.py`/`test_transfer_ai_hitl_flow.py` already draw: the
LLM-backed sub-graphs (document analysis, drafting, routing) are mocked,
and the router's own decision (item 1) or the assistant model's own tool
call (item 2) is scripted rather than left to a real model -- whether a
message *should* trigger a handoff is a router-calibration/prompt concern,
not what this file proves. What this file proves is that once either
signal fires, the turn actually runs draft, not just marks it as decided.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.llms.base import ToolCallResponse
from app.ai.workflows.planner import PlanDecision
from app.ai.workflows.planning_graph import create_planning_graph
from app.core.config import settings
from app.observability.ai_metrics import ROUTER_ASSIST_HANDOFFS

DRAFT_RESULT = {
    "status": "COMPLETED",
    "draft": "Konu: Test\n\nSayın Makam,\n\nArz ederim.\n\nAli Veli\nGenel Müdür",
    "correspondence_type": "response_letter",
    "combined_score": 90.0,
    "confidence_score": 90.0,
    "classification": {"summary": "Test."},
    "context": "",
    "source_document": "",
    "correspondence_type_source": "explicit",
    "style_examples": [],
}


def _handoffs_total(reason: str, target: str) -> float:
    return ROUTER_ASSIST_HANDOFFS.labels(reason=reason, target=target)._value.get()


def _build_graph(fake_llm, fake_fast_llm):
    document_analysis_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "document_type": "official_letter", "document_type_label": "Resmî Yazı",
                "summary": "Test evrakı.", "fields": {}, "missing_fields": [],
                "compliance_status": "compliant", "mevzuat_suggestions": [],
            }
        )
    )
    draft_graph = AsyncMock(ainvoke=AsyncMock(return_value=dict(DRAFT_RESULT)))
    routing_graph = AsyncMock(
        ainvoke=AsyncMock(
            return_value={
                "routed_unit": "İnsan Kaynakları Daire Başkanlığı", "priority": "Normal",
                "reasoning": "Test gerekçesi.", "justification": "Test gerekçesi.",
            }
        )
    )
    graph = create_planning_graph(
        llm_client=fake_llm, fast_llm_client=fake_fast_llm,
        document_analysis_graph=document_analysis_graph, rag_graph=AsyncMock(),
        draft_graph=draft_graph, routing_graph=routing_graph, checkpointer=MemorySaver(),
    )
    return graph, draft_graph


@pytest.mark.asyncio
async def test_a_fallback_sourced_assist_decision_is_redirected_to_draft(
    fake_llm, fake_fast_llm, monkeypatch
):
    """Item 1: the router itself decided "assist" only because nothing else
    was decisive (source="model_failed") -- the deterministic re-score finds
    strong lexical draft evidence the fallback missed, and the assist step
    is skipped entirely (the model is never even called)."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    before = _handoffs_total("fallback_source", "draft")

    async def _fake_resolve_plan(*args, **kwargs):
        return PlanDecision(
            steps=["assist"], intent="assist", reasoning="test", source="model_failed",
        )

    monkeypatch.setattr(
        "app.ai.workflows.planning_graph.resolve_plan", _fake_resolve_plan
    )
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "assist-handoff-1"}}

    result = await graph.ainvoke(
        {"input_text": "Bu evraka bir cevap yazısı hazırla.", "document_id": None}, config=config
    )

    assert draft_graph.ainvoke.await_count == 1
    assert fake_llm.stream_calls == []
    assert fake_llm.generate_with_tools_calls == []
    assert result["final_output"]["draft"]["draft"] == DRAFT_RESULT["draft"]
    assert _handoffs_total("fallback_source", "draft") == before + 1


@pytest.mark.asyncio
async def test_a_confident_assist_decision_is_never_redirected(fake_llm, fake_fast_llm, monkeypatch):
    """Control for the test above -- a genuinely confident "assist" decision
    (source="fused") must run assist normally, never pre-empted."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)

    async def _fake_resolve_plan(*args, **kwargs):
        return PlanDecision(
            steps=["assist"], intent="assist", reasoning="test", source="fused", confidence=0.95,
        )

    monkeypatch.setattr(
        "app.ai.workflows.planning_graph.resolve_plan", _fake_resolve_plan
    )
    fake_llm.generate_with_tools_side_effect = [ToolCallResponse(content="Merhaba! Nasıl yardımcı olabilirim?")]
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "assist-handoff-2"}}

    result = await graph.ainvoke(
        {"input_text": "Bu evraka bir cevap yazısı hazırla.", "document_id": None}, config=config
    )

    assert draft_graph.ainvoke.await_count == 0
    assert result["final_output"]["assist"]["reply"] == "Merhaba! Nasıl yardımcı olabilirim?"


@pytest.mark.asyncio
async def test_the_assistant_models_own_handoff_tool_call_redirects_to_draft(
    fake_llm, fake_fast_llm, monkeypatch
):
    """Item 2: the router confidently sent this to assist, but the model
    itself recognizes (via request_handoff) that the message actually
    belongs to draft -- the turn still ends up running draft this turn."""
    monkeypatch.setattr(settings, "HITL_BRIEF_GATE_ENABLED", False)
    before = _handoffs_total("model_tool", "draft")

    async def _fake_resolve_plan(*args, **kwargs):
        return PlanDecision(
            steps=["assist"], intent="assist", reasoning="test", source="fused", confidence=0.9,
        )

    monkeypatch.setattr(
        "app.ai.workflows.planning_graph.resolve_plan", _fake_resolve_plan
    )
    fake_llm.generate_with_tools_side_effect = [
        ToolCallResponse(
            tool_calls=[
                {
                    "name": "request_handoff",
                    "args": {"target": "draft", "reason": "aslında taslak isteği"},
                    "id": "1",
                }
            ]
        ),
        ToolCallResponse(content="Taslağınızı hazırlıyorum."),
    ]
    graph, draft_graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "assist-handoff-3"}}

    result = await graph.ainvoke(
        {"input_text": "Belirsiz bir mesaj.", "document_id": None}, config=config
    )

    assert draft_graph.ainvoke.await_count == 1
    assert result["final_output"]["draft"]["draft"] == DRAFT_RESULT["draft"]
    assert _handoffs_total("model_tool", "draft") == before + 1
