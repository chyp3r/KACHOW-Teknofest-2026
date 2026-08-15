"""End-to-end proof that a company's runtime style adapter (Faz C2, #185)
actually reaches the writer/reviser prompt -- and that a name leaking out of
one of its preferred_examples is caught by the same deterministic
ornek_sizintisi check retrieved style_examples already go through.

Exercises the real compiled draft/revise graphs (writer/reviser streaming is
mocked, everything else -- verification, the adapter_provider plumbing --
runs for real), same style as test_draft_loop.py/test_revise_graph.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.adapters.company_adapter import CompanyAdapter
from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.llms.base import BaseLLMClient
from app.ai.session.focus import DraftVersion
from app.ai.workflows.draft_graph import create_draft_graph
from app.ai.workflows.revise_graph import create_revise_graph
from app.core.config import settings

GOOD_DRAFT = (
    "Konu: Test Konusu\n"
    "Sayı: E-1-1\n"
    "Tarih: 30.07.2026\n\n"
    "Sayın Makam,\n\n"
    "Arz ederim.\n\n"
    "Ali Veli\nGenel Müdür"
)

DRAFT_BASE_STATE = {
    "source_document": "Sayı: E-1-1, Tarih: 30.07.2026 tarihli evrak.",
    "classification": {
        "document_type_label": "Resmî Yazı",
        "summary": "Test evrakı.",
        "fields": {},
        "missing_fields": [],
    },
    "correspondence_type": "cover_letter",
    "context": "İlgili mevzuat metni burada.",
    "instructions": "Test talimatı.",
    "company_id": "company-1",
}


async def _one_chunk(text: str):
    yield text


def _mock_llm_client() -> MagicMock:
    client = MagicMock(spec=BaseLLMClient)
    client.count_tokens = MagicMock(return_value=1)
    return client


@pytest.fixture(autouse=True)
def _disable_judge(monkeypatch):
    monkeypatch.setattr(settings, "DRAFT_JUDGE_ENABLED", False)


def _adapter(**overrides) -> CompanyAdapter:
    fields = dict(
        company_id="company-1",
        version=1,
        style_rules=("Kapanışta her zaman 'Arz ederim' kullan.",),
        avoided_patterns=("Edilgen çatı kullanma.",),
    )
    fields.update(overrides)
    return CompanyAdapter(**fields)


# ==========================================
# draft_graph
# ==========================================
async def test_writer_prompt_carries_the_companys_adapter_block():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    adapter_provider = AsyncMock(return_value=_adapter())
    graph = create_draft_graph(_mock_llm_client(), adapter_provider=adapter_provider)

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    adapter_provider.assert_awaited_once_with("company-1")
    assert captured_prompts, "writer prompt was never captured"
    prompt = captured_prompts[0]
    assert "BU ŞİRKETE ÖZGÜ YAZIM TERCİHLERİ" in prompt
    assert "Kapanışta her zaman 'Arz ederim' kullan." in prompt
    assert "Edilgen çatı kullanma." in prompt


async def test_writer_prompt_carries_no_adapter_block_when_none_is_configured():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    graph = create_draft_graph(_mock_llm_client())  # no adapter_provider at all

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    assert captured_prompts
    assert "BU ŞİRKETE ÖZGÜ YAZIM TERCİHLERİ" not in captured_prompts[0]


async def test_a_failing_adapter_provider_degrades_to_no_block_not_a_crash():
    adapter_provider = AsyncMock(side_effect=RuntimeError("redis down"))
    graph = create_draft_graph(_mock_llm_client(), adapter_provider=adapter_provider)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(DRAFT_BASE_STATE)

    assert result["status"] == "COMPLETED"


async def test_a_company_name_leaking_from_a_preferred_example_is_flagged_as_example_leak():
    """The critical boundary the plan calls out explicitly: preferred_examples
    are real generated text and must be caught by the exact same
    ornek_sizintisi check style_examples already goes through -- a name from
    one leaking into the draft must force human review, never ship quietly.

    Same institution-name shape test_draft_verifier.py's own
    test_a_value_only_present_in_a_style_example_is_flagged_as_a_leak uses
    directly against verify_draft -- reused here so the claim-extraction
    regex is known to actually fire, and what's under test is purely
    whether the adapter's preferred_examples reach that same haystack.
    """
    leaking_adapter = _adapter(
        preferred_examples=("Bu örnek yazı Bursa Kaymakamlığı tarafından hazırlanmıştır.",)
    )
    draft_with_leak = (
        "Konu: Yıllık İzin Talebi\n"
        "Sayı: E-1-1\n"
        "Tarih: 30.07.2026\n\n"
        "Sayın Makam, konu hakkında yerel şubemiz Bursa Kaymakamlığı'na bilgi vermiştir.\n\n"
        "Arz ederim.\n\n"
        "Ali Veli\nGenel Müdür"
    )
    adapter_provider = AsyncMock(return_value=leaking_adapter)
    graph = create_draft_graph(_mock_llm_client(), adapter_provider=adapter_provider)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(draft_with_leak)
        result = await graph.ainvoke(DRAFT_BASE_STATE)

    applied_rule_ids = {rule["rule_id"] for rule in result["applied_rules"]}
    assert "ornek_sizintisi" in applied_rule_ids
    assert result["requires_human_approval"] is True


# ==========================================
# revise_graph
# ==========================================
def _active_draft(**overrides) -> DraftVersion:
    fields = dict(
        version=1,
        text=GOOD_DRAFT,
        correspondence_type="cover_letter",
        confidence_score=90.0,
        created_from="draft",
        classification={"summary": "Test evrakı.", "fields": {}},
        context="İlgili mevzuat metni.",
        source_document="Kaynak evrak metni.",
        style_examples=(),
        correspondence_type_source="",
    )
    fields.update(overrides)
    return DraftVersion(**fields)


async def test_reviser_prompt_carries_the_companys_adapter_block():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT.replace("Sayın Makam", "Sayın Yeni Makam")):
            yield chunk

    adapter_provider = AsyncMock(return_value=_adapter())
    graph = create_revise_graph(_mock_llm_client(), adapter_provider=adapter_provider)

    with patch.object(ReviserAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(
            {
                "active_draft": _active_draft(),
                "instructions": "Muhatabı 'Yeni Makam' olarak değiştir.",
                "reasoning_level": "fast",
                "company_id": "company-1",
            }
        )

    adapter_provider.assert_awaited_once_with("company-1")
    assert captured_prompts
    assert "BU ŞİRKETE ÖZGÜ YAZIM TERCİHLERİ" in captured_prompts[0]
