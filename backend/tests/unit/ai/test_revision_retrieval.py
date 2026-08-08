"""Unit tests for the conditional legislation re-retrieval a revision may
trigger. Every scenario asserts the degrade-safe contract: on skip, timeout
or failure, the draft's frozen context is returned unchanged."""

import asyncio

import pytest
from langchain_core.documents import Document

from app.ai.revision.instruction import parse_revision_instruction
from app.ai.revision.retrieval import maybe_extend_context
from app.ai.session.focus import DraftVersion


class _FakeRetriever:
    def __init__(self, documents=None, *, raises=None, hang=False):
        self.documents = documents or []
        self.raises = raises
        self.hang = hang
        self.calls: list[dict] = []

    async def retrieve(self, query, limit):
        self.calls.append({"query": query, "limit": limit})
        if self.hang:
            await asyncio.sleep(10)
        if self.raises is not None:
            raise self.raises
        return self.documents


def _active_draft(**overrides) -> DraftVersion:
    defaults = dict(
        version=1, text="taslak metni", correspondence_type="response_letter",
        confidence_score=90.0, created_from="draft",
        classification={"fields": {"konu": "izin talebi"}}, context="",
        source_document="",
    )
    defaults.update(overrides)
    return DraftVersion(**defaults)


@pytest.mark.asyncio
async def test_a_tone_only_instruction_skips_retrieval_entirely():
    instruction = parse_revision_instruction("Daha resmi yap.")
    retriever = _FakeRetriever(documents=[Document(page_content="ilgisiz", metadata={})])
    active_draft = _active_draft(context="mevcut baglam")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
    )

    assert context == "mevcut baglam"
    assert meta["decision"] == "skipped"
    assert retriever.calls == []


@pytest.mark.asyncio
async def test_no_retriever_configured_skips_even_for_a_normative_instruction():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    active_draft = _active_draft(context="mevcut baglam")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=None,
    )

    assert context == "mevcut baglam"
    assert meta["decision"] == "skipped"


@pytest.mark.asyncio
async def test_a_normative_instruction_extends_the_frozen_context():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    retriever = _FakeRetriever(
        documents=[Document(page_content="4982 sayılı Kanun madde 5...", metadata={"mevzuat": "4982 sayılı Kanun"})]
    )
    active_draft = _active_draft(context="[ALINTI 1] (Kaynak: Eski Kanun)\nEski metin.")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
    )

    assert meta["decision"] == "extended"
    assert meta["added"] == 1
    assert "[ALINTI 1] (Kaynak: Eski Kanun)" in context
    assert "[ALINTI 2]" in context
    assert "4982 sayılı Kanun madde 5" in context
    assert retriever.calls[0]["query"]  # a non-empty query was issued


@pytest.mark.asyncio
async def test_an_already_present_excerpt_is_not_duplicated():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    frozen = "[ALINTI 1] (Kaynak: 4982 sayılı Kanun)\nZaten burada olan metin."
    retriever = _FakeRetriever(
        documents=[Document(page_content="Zaten burada olan metin.", metadata={"mevzuat": "4982 sayılı Kanun"})]
    )
    active_draft = _active_draft(context=frozen)

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
    )

    assert context == frozen
    assert meta["decision"] == "skipped"
    assert meta["added"] == 0


@pytest.mark.asyncio
async def test_a_retriever_failure_degrades_to_the_frozen_context():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    retriever = _FakeRetriever(raises=RuntimeError("qdrant down"))
    active_draft = _active_draft(context="mevcut baglam")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
    )

    assert context == "mevcut baglam"
    assert meta["decision"] == "failed"


@pytest.mark.asyncio
async def test_a_timeout_degrades_to_the_frozen_context():
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    retriever = _FakeRetriever(hang=True)
    active_draft = _active_draft(context="mevcut baglam")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
        timeout_s=0.01,
    )

    assert context == "mevcut baglam"
    assert meta["decision"] == "failed"


@pytest.mark.asyncio
async def test_the_setting_disables_reretrieval_even_for_a_normative_instruction(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "REVISION_RERETRIEVAL_ENABLED", False)
    instruction = parse_revision_instruction("4982 sayılı Kanuna atıf ekle.")
    retriever = _FakeRetriever(documents=[Document(page_content="x", metadata={})])
    active_draft = _active_draft(context="mevcut baglam")

    context, meta = await maybe_extend_context(
        instruction=instruction, active_draft=active_draft, retriever=retriever,
    )

    assert context == "mevcut baglam"
    assert meta["decision"] == "skipped"
    assert retriever.calls == []
