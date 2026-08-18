"""End-to-end proof that a company's mandatory drafting rules (#214) and
identity profile actually reach the writer/reviser prompt, mirroring
test_company_adapter_prompt_injection.py's own style and fixtures.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.adapters.company_rules import CompanyRule, CompanyRuleSet
from app.ai.agents.reviser import ReviserAgent
from app.ai.agents.writer import WriterAgent
from app.ai.identity.company_profile import CompanyProfile
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


def _ruleset(**overrides) -> CompanyRuleSet:
    fields = dict(
        company_id="company-1",
        version=1,
        rules=(
            CompanyRule(id="K1", text="Kapanışta her zaman 'Arz ederim' kullan."),
            CompanyRule(id="K2", text="Kısa paragraflar tercih et.", severity="onerilen"),
        ),
    )
    fields.update(overrides)
    return CompanyRuleSet(**fields)


# ==========================================
# draft_graph
# ==========================================
async def test_writer_prompt_carries_the_companys_rules_block():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    rules_provider = AsyncMock(return_value=_ruleset())
    graph = create_draft_graph(_mock_llm_client(), rules_provider=rules_provider)

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    rules_provider.assert_awaited_once_with("company-1")
    assert captured_prompts, "writer prompt was never captured"
    prompt = captured_prompts[0]
    assert "ŞİRKETE ÖZGÜ ZORUNLU KURALLAR" in prompt
    assert "[K1] Kapanışta her zaman 'Arz ederim' kullan." in prompt
    assert "[K2] Kısa paragraflar tercih et." in prompt


async def test_rules_block_precedes_the_adapter_block_in_the_writer_prompt():
    """A mandatory rule outranks a learned style preference -- see
    draft_graph._build_repair_prompt's own docstring on this ordering."""
    from app.ai.adapters.company_adapter import CompanyAdapter

    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    rules_provider = AsyncMock(return_value=_ruleset())
    adapter_provider = AsyncMock(
        return_value=CompanyAdapter(
            company_id="company-1", style_rules=("Bir üslup tercihi.",)
        )
    )
    graph = create_draft_graph(
        _mock_llm_client(), adapter_provider=adapter_provider, rules_provider=rules_provider
    )

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    prompt = captured_prompts[0]
    assert prompt.index("ŞİRKETE ÖZGÜ ZORUNLU KURALLAR") < prompt.index(
        "BU ŞİRKETE ÖZGÜ YAZIM TERCİHLERİ"
    )


async def test_writer_prompt_carries_no_rules_block_when_none_is_configured():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    graph = create_draft_graph(_mock_llm_client())  # no rules_provider at all

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    assert captured_prompts
    assert "ŞİRKETE ÖZGÜ ZORUNLU KURALLAR" not in captured_prompts[0]


async def test_a_failing_rules_provider_degrades_to_no_block_not_a_crash():
    rules_provider = AsyncMock(side_effect=RuntimeError("redis down"))
    graph = create_draft_graph(_mock_llm_client(), rules_provider=rules_provider)

    with patch.object(WriterAgent, "stream") as mock_writer:
        mock_writer.side_effect = lambda **kwargs: _one_chunk(GOOD_DRAFT)
        result = await graph.ainvoke(DRAFT_BASE_STATE)

    assert result["status"] == "COMPLETED"


async def test_writer_prompt_carries_the_companys_identity_section():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT):
            yield chunk

    profile_provider = AsyncMock(
        return_value=CompanyProfile(
            company_id="company-1",
            display_name="Acme A.Ş.",
            letterhead="T.C.\nACME A.Ş.",
            default_signer_title="Daire Başkanı",
        )
    )
    graph = create_draft_graph(_mock_llm_client(), profile_provider=profile_provider)

    with patch.object(WriterAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(DRAFT_BASE_STATE)

    profile_provider.assert_awaited_once_with("company-1")
    assert captured_prompts
    assert "KURUM KİMLİĞİ" in captured_prompts[0]
    assert "Acme A.Ş." in captured_prompts[0]


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


async def test_reviser_prompt_carries_the_companys_rules_block():
    captured_prompts: list[str] = []

    async def _capture_and_stream(**kwargs):
        captured_prompts.append(kwargs["messages"])
        async for chunk in _one_chunk(GOOD_DRAFT.replace("Sayın Makam", "Sayın Yeni Makam")):
            yield chunk

    rules_provider = AsyncMock(return_value=_ruleset())
    graph = create_revise_graph(_mock_llm_client(), rules_provider=rules_provider)

    with patch.object(ReviserAgent, "stream", side_effect=_capture_and_stream):
        await graph.ainvoke(
            {
                "active_draft": _active_draft(),
                "instructions": "Muhatabı 'Yeni Makam' olarak değiştir.",
                "reasoning_level": "fast",
                "company_id": "company-1",
            }
        )

    rules_provider.assert_awaited_once_with("company-1")
    assert captured_prompts
    assert "ŞİRKETE ÖZGÜ ZORUNLU KURALLAR" in captured_prompts[0]
