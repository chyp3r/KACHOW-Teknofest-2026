import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.documents import Document

from app.ai.workflows import (
    create_classification_graph,
    create_rag_graph,
    create_draft_graph,
    create_routing_graph,
    create_system_graph,
    create_planning_graph,
)
from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.infrastructure.cache.redis import RedisCache
from app.ai.workflows.classification_graph import ClassificationOutput, NEROutput, MetadataOutput
from app.ai.workflows.rag_graph import QueryRewriteOutput, VerifierOutput
from app.ai.workflows.draft_graph import EditorOutput, EvaluatorOutput
from app.ai.workflows.routing_graph import RouteOutput
from app.ai.workflows.planning_graph import PlanOutput



# ==========================================
# Classification Graph Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.classifier.ClassifierAgent.run_structured")
@patch("app.ai.agents.ner.NERAgent.run_structured")
@patch("app.ai.agents.metadata.MetadataAgent.run_structured")
async def test_classification_graph(mock_meta_run, mock_ner_run, mock_class_run):
    # Setup mocks
    mock_class_run.return_value = ClassificationOutput(doc_type="Dilekçe", summary="İzin talebi özeti.")
    mock_ner_run.return_value = NEROutput(people=["Ahmet Yılmaz"], organizations=["ASELSAN"], dates=["29 Temmuz"])
    mock_meta_run.return_value = MetadataOutput(metadata={"konu": "İzin"})
    
    mock_llm = MagicMock(spec=BaseLLMClient)
    graph = create_classification_graph(mock_llm)
    
    res = await graph.ainvoke({"input_text": "Ahmet Yılmaz 29 Temmuz tarihinde ASELSAN'da izin istiyor."})
    
    assert res["doc_type"] == "Dilekçe"
    assert res["summary"] == "İzin talebi özeti."
    assert res["entities"]["people"] == ["Ahmet Yılmaz"]
    assert res["metadata"]["konu"] == "İzin"
    assert res["next_workflow_state"] == "RAG"


# ==========================================
# RAG Graph Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.verifier.VerifierAgent.run_structured")
async def test_rag_graph(mock_verifier_run):
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_retriever = AsyncMock(spec=HybridRetriever)
    
    doc = Document(page_content="Türkiye'de şeker pancarı yaygındır.", metadata={})
    mock_retriever.retrieve.return_value = [doc]
    
    # Attempt 1: Query rewrite output
    # Note: verifier agent is called for BOTH rewrite (structured) and verify (structured)
    # We will set a side effect to return rewrite output on first call, verify output on second call
    mock_verifier_run.side_effect = [
        QueryRewriteOutput(rewritten_query="şeker pancarı üretimi türkiye"),
        VerifierOutput(status="SUFFICIENT", feedback="Bilgi yeterli")
    ]
    
    graph = create_rag_graph(mock_llm, mock_retriever)
    
    res = await graph.ainvoke({"original_query": "Şeker pancarı nerede yetişir?", "attempts": 0})
    
    assert res["rewritten_query"] == "şeker pancarı üretimi türkiye"
    assert len(res["documents"]) == 1
    assert res["documents"][0].page_content == "Türkiye'de şeker pancarı yaygındır."
    assert res["verification_status"] == "SUFFICIENT"


# ==========================================
# Draft Graph Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_llm = MagicMock(spec=BaseLLMClient)

    mock_writer_run.return_value = "Draft content text."
    mock_editor_struct.return_value = EditorOutput(
        needs_revision=False, feedback="İyi taslak."
    )
    mock_reflection_run.return_value = "Self-critiqued draft."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="Refined final draft.", confidence_score=95.0
    )

    graph = create_draft_graph(mock_llm)

    res = await graph.ainvoke(
        {"context": "Some context", "instructions": "Write official letter", "attempts": 0}
    )

    assert res["draft"] == "Refined final draft."
    assert res["confidence_score"] == 95.0


# ==========================================
# Routing Graph Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.router.RouterAgent.run_structured")
async def test_routing_graph(mock_router_run):
    mock_router_run.return_value = RouteOutput(destination="HR", justification="İzin konusudur.")
    mock_llm = MagicMock(spec=BaseLLMClient)
    
    graph = create_routing_graph(mock_llm)
    res = await graph.ainvoke({"draft": "Personel izin belgesi.", "confidence_score": 90.0})
    
    assert res["final_destination"] == "HR"
    assert res["justification"] == "İzin konusudur."


# ==========================================
# System Graph Test
# ==========================================
@pytest.mark.asyncio
async def test_system_graph():
    mock_redis = AsyncMock(spec=RedisCache)
    graph = create_system_graph(mock_redis)
    
    res = await graph.ainvoke({
        "action_type": "CACHE_UPDATE",
        "payload": {"key": "test_key", "value": "test_val"},
        "logs": []
    })
    
    assert res["status"] == "SUCCESS"
    assert "Successfully cached key 'test_key'." in res["logs"]
    mock_redis.set.assert_called_once_with("test_key", "test_val")


# ==========================================
# Planning Graph (Master Supervisor) Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.orchestrator.OrchestratorAgent.run_structured")
async def test_planning_master_graph(mock_orch_run):
    mock_llm = MagicMock(spec=BaseLLMClient)
    
    # 1. Mock Supervisor planning steps output
    mock_orch_run.return_value = PlanOutput(
        required_steps=["classification", "rag"],
        reasoning="Belge geldiği için önce sınıflandırma, sonra RAG gerekiyor."
    )
    
    # 2. Mock sub-graphs
    mock_class_graph = AsyncMock()
    mock_class_graph.ainvoke.return_value = {"doc_type": "Dilekçe", "summary": "İzin talebi."}
    
    mock_rag_graph = AsyncMock()
    mock_rag_graph.ainvoke.return_value = {"context": "Şeker pancarı bilgisi."}
    
    mock_draft_graph = AsyncMock()
    mock_routing_graph = AsyncMock()
    
    master_graph = create_planning_graph(
        llm_client=mock_llm,
        classification_graph=mock_class_graph,
        rag_graph=mock_rag_graph,
        draft_graph=mock_draft_graph,
        routing_graph=mock_routing_graph
    )
    
    res = await master_graph.ainvoke({"input_text": "Yeni gelen evrak içeriği"})
    
    assert res["plan_steps"] == ["classification", "rag"]
    assert res["classification_result"]["doc_type"] == "Dilekçe"
    assert res["rag_result"]["context"] == "Şeker pancarı bilgisi."
    
    final_output = res["final_output"]
    assert final_output["status"] == "COMPLETED"
    assert final_output["classification"]["doc_type"] == "Dilekçe"
    assert final_output["rag"]["context"] == "Şeker pancarı bilgisi."
