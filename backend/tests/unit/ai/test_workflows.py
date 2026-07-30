from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from app.ai.llms.base import BaseLLMClient
from app.ai.retrieval.hybrid import HybridRetriever
from app.ai.workflows import (
    create_draft_graph,
    create_planning_graph,
    create_rag_graph,
    create_routing_graph,
    create_system_graph,
)
from app.ai.workflows.correspondence import resolve_correspondence_type
from app.ai.workflows.draft_graph import EditorOutput, EvaluatorOutput
from app.ai.workflows.planning_graph import PlanOutput
from app.ai.workflows.rag_graph import QueryRewriteOutput, VerifierOutput
from app.ai.workflows.routing_graph import RouteOutput
from app.core.enums.correspondence_type import CorrespondenceType
from app.infrastructure.cache.redis import RedisCache


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
        VerifierOutput(status="SUFFICIENT", feedback="Bilgi yeterli"),
    ]

    graph = create_rag_graph(mock_llm, mock_retriever)

    res = await graph.ainvoke(
        {"original_query": "Şeker pancarı nerede yetişir?", "attempts": 0}
    )

    assert res["rewritten_query"] == "şeker pancarı üretimi türkiye"
    assert len(res["documents"]) == 1
    assert res["documents"][0].page_content == "Türkiye'de şeker pancarı yaygındır."
    assert res["verification_status"] == "SUFFICIENT"


# ==========================================
# Draft Graph Test
# ==========================================
@pytest.mark.parametrize(
    (
        "requested_type",
        "instructions",
        "classification",
        "expected_type",
        "expected_source",
    ),
    [
        (
            None,
            "Resmî metin hazırla.",
            {"metadata": {"correspondence_type": "üst yazı"}},
            CorrespondenceType.COVER_LETTER,
            "classification",
        ),
        (
            None,
            "Bilgilendirme metni hazırla.",
            {"doc_type": "Dilekçe"},
            CorrespondenceType.INFORMATION_NOTICE,
            "instructions",
        ),
        (
            None,
            "Uygun resmî metni hazırla.",
            {"doc_type": "Duyuru"},
            CorrespondenceType.INFORMATION_NOTICE,
            "document_type",
        ),
    ],
)
def test_correspondence_type_resolution_precedence(
    requested_type,
    instructions,
    classification,
    expected_type,
    expected_source,
):
    resolved_type, source = resolve_correspondence_type(
        requested_type,
        instructions,
        classification,
    )

    assert resolved_type == expected_type
    assert source == expected_source


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
        {
            "source_document": "Ahmet Yılmaz 29 Temmuz için izin talep ediyor.",
            "classification": {
                "doc_type": "Dilekçe",
                "entities": {"people": ["Ahmet Yılmaz"], "dates": ["29 Temmuz"]},
            },
            "context": "İzin talepleri İnsan Kaynakları tarafından değerlendirilir.",
            "instructions": "Write official letter",
            "attempts": 0,
        }
    )

    assert res["draft"] == "Refined final draft."
    assert res["confidence_score"] == 95.0
    assert res["requires_human_approval"] is False
    assert res["correspondence_type"] == CorrespondenceType.RESPONSE_LETTER
    assert res["correspondence_type_source"] == "document_type"
    assert res["status"] == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_type", "expected_type", "prompt_fragment"),
    [
        ("üst yazı", CorrespondenceType.COVER_LETTER, "İletilen ek veya dayanak"),
        (
            "cevap yazısı",
            CorrespondenceType.RESPONSE_LETTER,
            "Gelen evraktaki talep veya soruyu",
        ),
        (
            "bilgilendirme metni",
            CorrespondenceType.INFORMATION_NOTICE,
            "Bilgiyi tarafsız",
        ),
        (
            "alternatif resmî yazışma",
            CorrespondenceType.OTHER_OFFICIAL,
            "esnek fakat resmî",
        ),
    ],
)
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_supports_official_correspondence_types(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
    requested_type,
    expected_type,
    prompt_fragment,
):
    mock_writer_run.return_value = "Türe uygun ilk taslak."
    mock_editor_struct.return_value = EditorOutput(
        needs_revision=False, feedback="Uygun."
    )
    mock_reflection_run.return_value = "Türe uygun nihai taslak."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="Türe uygun nihai taslak.",
        confidence_score=94.0,
    )

    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))
    res = await graph.ainvoke(
        {
            "source_document": "Kuruma iletilen doğrulanmış evrak.",
            "classification": {"doc_type": "Resmî Yazı"},
            "correspondence_type": requested_type,
            "context": "Doğrulanmış kurumsal bağlam.",
            "instructions": "Uygun resmî yazışmayı hazırla.",
        }
    )

    writer_prompt = mock_writer_run.call_args.kwargs["messages"]
    assert expected_type.value in writer_prompt
    assert prompt_fragment in writer_prompt
    assert expected_type.value in mock_editor_struct.call_args.kwargs["messages"]
    assert expected_type.value in mock_reflection_run.call_args.kwargs["messages"]
    assert expected_type.value in mock_evaluator_struct.call_args.kwargs["messages"]
    assert res["correspondence_type"] == expected_type
    assert res["correspondence_type_source"] == "explicit"
    assert res["requires_human_approval"] is False
    assert res["status"] == "COMPLETED"


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_requires_approval_for_unknown_correspondence_type(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_writer_run.return_value = "İnsan incelemesi gerektiren taslak."
    mock_editor_struct.return_value = EditorOutput(
        needs_revision=False, feedback="Biçim uygun."
    )
    mock_reflection_run.return_value = "İnsan incelemesi gerektiren nihai taslak."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="İnsan incelemesi gerektiren nihai taslak.",
        confidence_score=95.0,
        requires_human_approval=False,
    )

    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))
    res = await graph.ainvoke(
        {
            "source_document": "Kuruma iletilen evrak.",
            "classification": {"doc_type": "Bilinmeyen"},
            "correspondence_type": "tanımsız yazışma",
            "context": "Doğrulanmış bağlam.",
            "instructions": "Resmî metin hazırla.",
        }
    )

    assert res["correspondence_type"] == CorrespondenceType.OTHER_OFFICIAL
    assert res["correspondence_type_source"] == "fallback"
    assert res["requires_human_approval"] is True
    assert res["status"] == "NEEDS_HUMAN_APPROVAL"


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_preserves_sources_during_revision(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_writer_run.side_effect = ["İlk taslak.", "Düzeltilmiş taslak."]
    mock_editor_struct.side_effect = [
        EditorOutput(needs_revision=True, feedback="Tarihi açıkça belirt."),
        EditorOutput(needs_revision=False, feedback="Uygun."),
    ]
    mock_reflection_run.return_value = "Kaynağa bağlı nihai taslak."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="Kaynağa bağlı nihai taslak.",
        confidence_score=92.0,
    )

    graph = create_draft_graph(mock_llm)
    res = await graph.ainvoke(
        {
            "source_document": "Başvuru sahibi 29 Temmuz tarihinde izin talep etmiştir.",
            "classification": {"doc_type": "Dilekçe"},
            "context": "İzin talebi ilgili birim tarafından değerlendirilir.",
            "instructions": "Resmi cevap hazırla.",
            "attempts": 0,
        }
    )

    assert mock_writer_run.call_count == 2
    revision_prompt = mock_writer_run.call_args_list[1].kwargs["messages"]
    assert "29 Temmuz tarihinde izin talep etmiştir" in revision_prompt
    assert "İzin talebi ilgili birim" in revision_prompt
    assert "Tarihi açıkça belirt" in revision_prompt
    assert res["attempts"] == 2
    assert res["status"] == "COMPLETED"


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
async def test_draft_graph_rejects_missing_source_document(mock_writer_run):
    mock_llm = MagicMock(spec=BaseLLMClient)
    graph = create_draft_graph(mock_llm)

    res = await graph.ainvoke(
        {
            "source_document": "   ",
            "classification": {},
            "context": "Bağlam",
            "instructions": "Resmi cevap hazırla.",
            "attempts": 0,
        }
    )

    mock_writer_run.assert_not_called()
    assert res["draft"] == ""
    assert res["confidence_score"] == 0.0
    assert res["requires_human_approval"] is True
    assert res["correspondence_type"] == CorrespondenceType.RESPONSE_LETTER
    assert res["status"] == "FAILED"
    assert "evrak içeriği" in res["error"]


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
async def test_draft_graph_stops_after_writer_failure(mock_writer_run):
    mock_writer_run.side_effect = RuntimeError("LLM unavailable")
    mock_llm = MagicMock(spec=BaseLLMClient)
    graph = create_draft_graph(mock_llm)

    res = await graph.ainvoke(
        {
            "source_document": "Kuruma gönderilmiş örnek evrak.",
            "classification": {"doc_type": "Resmi Yazı"},
            "context": "Doğrulanmış bağlam.",
            "instructions": "Resmi cevap hazırla.",
            "attempts": 0,
        }
    )

    assert res["draft"] == ""
    assert res["confidence_score"] == 0.0
    assert res["requires_human_approval"] is True
    assert res["status"] == "FAILED"
    assert "LLM unavailable" in res["error"]


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_requires_approval_without_verified_context(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_writer_run.return_value = "Kaynak evraka dayalı taslak."
    mock_editor_struct.return_value = EditorOutput(
        needs_revision=False, feedback="Uygun."
    )
    mock_reflection_run.return_value = "Kaynak evraka dayalı nihai taslak."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="Kaynak evraka dayalı nihai taslak.",
        confidence_score=95.0,
        requires_human_approval=False,
    )

    graph = create_draft_graph(mock_llm)
    res = await graph.ainvoke(
        {
            "source_document": "Eksik bilgi içeren gelen evrak.",
            "classification": {"doc_type": "Dilekçe"},
            "context": "",
            "instructions": "Resmi cevap hazırla.",
            "attempts": 0,
        }
    )

    assert res["confidence_score"] == 95.0
    assert res["requires_human_approval"] is True
    assert res["status"] == "NEEDS_HUMAN_APPROVAL"


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_requires_approval_when_revision_limit_is_reached(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_llm = MagicMock(spec=BaseLLMClient)
    mock_writer_run.side_effect = ["İlk taslak.", "İkinci taslak."]
    mock_editor_struct.side_effect = [
        EditorOutput(needs_revision=True, feedback="İlk düzeltme."),
        EditorOutput(needs_revision=True, feedback="Hâlâ doğrulanamayan bilgi var."),
    ]
    mock_reflection_run.return_value = "İnceleme gerektiren taslak."
    mock_evaluator_struct.return_value = EvaluatorOutput(
        final_draft="İnceleme gerektiren taslak.",
        confidence_score=90.0,
    )

    graph = create_draft_graph(mock_llm)
    res = await graph.ainvoke(
        {
            "source_document": "Gelen evrak.",
            "classification": {"doc_type": "Dilekçe"},
            "context": "Doğrulanmış bağlam.",
            "instructions": "Resmi cevap hazırla.",
            "attempts": 0,
        }
    )

    assert mock_writer_run.call_count == 2
    assert res["attempts"] == 2
    assert res["requires_human_approval"] is True
    assert res["status"] == "NEEDS_HUMAN_APPROVAL"


@pytest.mark.asyncio
@patch("app.ai.agents.writer.WriterAgent.run")
@patch("app.ai.agents.editor.EditorAgent.run_structured")
@patch("app.ai.agents.reflection.ReflectionAgent.run")
@patch("app.ai.agents.evaluator.EvaluatorAgent.run_structured")
async def test_draft_graph_preserves_draft_when_evaluator_fails(
    mock_evaluator_struct,
    mock_reflection_run,
    mock_editor_struct,
    mock_writer_run,
):
    mock_writer_run.return_value = "İlk taslak."
    mock_editor_struct.return_value = EditorOutput(
        needs_revision=False, feedback="Uygun."
    )
    mock_reflection_run.return_value = "Kaynağa dayalı son taslak."
    mock_evaluator_struct.side_effect = ValueError("Geçersiz yapılandırılmış çıktı")

    graph = create_draft_graph(MagicMock(spec=BaseLLMClient))
    res = await graph.ainvoke(
        {
            "source_document": "Başvuru sahibinin talebi.",
            "classification": {"document_type": "başvuru"},
            "context": "Doğrulanmış kurum bilgisi.",
            "instructions": "Resmî yanıt hazırla.",
        }
    )

    assert res["draft"] == "Kaynağa dayalı son taslak."
    assert res["confidence_score"] == 0.0
    assert res["requires_human_approval"] is True
    assert res["status"] == "NEEDS_HUMAN_APPROVAL"
    assert "Geçersiz yapılandırılmış çıktı" in res["error"]


def test_evaluator_output_rejects_out_of_range_confidence_score():
    with pytest.raises(ValidationError):
        EvaluatorOutput(final_draft="Taslak", confidence_score=101.0)


# ==========================================
# Routing Graph Test
# ==========================================
@pytest.mark.asyncio
@patch("app.ai.agents.router.RouterAgent.run_structured")
async def test_routing_graph(mock_router_run):
    mock_router_run.return_value = RouteOutput(
        destination="HR", justification="İzin konusudur."
    )
    mock_llm = MagicMock(spec=BaseLLMClient)

    graph = create_routing_graph(mock_llm)
    res = await graph.ainvoke(
        {"draft": "Personel izin belgesi.", "confidence_score": 90.0}
    )

    assert res["final_destination"] == "HR"
    assert res["justification"] == "İzin konusudur."


# ==========================================
# System Graph Test
# ==========================================
@pytest.mark.asyncio
async def test_system_graph():
    mock_redis = AsyncMock(spec=RedisCache)
    graph = create_system_graph(mock_redis)

    res = await graph.ainvoke(
        {
            "action_type": "CACHE_UPDATE",
            "payload": {"key": "test_key", "value": "test_val"},
            "logs": [],
        }
    )

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
        required_steps=["classification", "rag", "draft"],
        reasoning="Belge geldiği için önce sınıflandırma, sonra RAG gerekiyor.",
    )

    # 2. Mock sub-graphs
    mock_class_graph = AsyncMock()
    mock_class_graph.ainvoke.return_value = {
        "doc_type": "Dilekçe",
        "summary": "İzin talebi.",
        "metadata": {"correspondence_type": "information_notice"},
    }

    mock_rag_graph = AsyncMock()
    mock_rag_graph.ainvoke.return_value = {"context": "Şeker pancarı bilgisi."}

    mock_draft_graph = AsyncMock()
    mock_draft_graph.ainvoke.return_value = {
        "draft": "Resmi cevap.",
        "confidence_score": 90.0,
        "requires_human_approval": False,
        "status": "COMPLETED",
    }
    mock_routing_graph = AsyncMock()

    master_graph = create_planning_graph(
        llm_client=mock_llm,
        document_analysis_graph=mock_class_graph,
        rag_graph=mock_rag_graph,
        draft_graph=mock_draft_graph,
        routing_graph=mock_routing_graph,
    )

    res = await master_graph.ainvoke({"input_text": "Yeni gelen evrak içeriği"})

    assert res["plan_steps"] == ["classification", "rag", "draft"]
    assert res["classification_result"]["doc_type"] == "Dilekçe"
    assert res["rag_result"]["context"] == "Şeker pancarı bilgisi."
    draft_input = mock_draft_graph.ainvoke.call_args.args[0]
    assert draft_input["source_document"] == "Yeni gelen evrak içeriği"
    assert draft_input["classification"]["doc_type"] == "Dilekçe"
    assert draft_input["correspondence_type"] == "information_notice"
    assert draft_input["context"] == "Şeker pancarı bilgisi."

    final_output = res["final_output"]
    assert final_output["status"] == "COMPLETED"
    assert final_output["classification"]["doc_type"] == "Dilekçe"
    assert final_output["rag"]["context"] == "Şeker pancarı bilgisi."
    assert final_output["draft"]["draft"] == "Resmi cevap."
