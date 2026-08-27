"""Proof that the assist step's prompt no longer silently overflows.

Before ContextBuilder, `history_summary`/`document_context` were substituted
into the assist prompt unconditionally and the verbatim history window was a
fixed 12 turns regardless of how large everything else already was --
`OLLAMA_NUM_CTX` (8192) could be exceeded with no visibility at all, and
Ollama truncates a too-large prompt from the beginning (the system prompt
and oldest history first). This seeds a checkpoint with a summary and a
backlog far larger than any real turn produces and asserts the assist step
still completes, and that what actually reached the model is bounded rather
than the raw oversized values.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph


def _build_graph(fake_llm, fake_fast_llm):
    return create_planning_graph(
        llm_client=fake_llm,
        document_analysis_graph=AsyncMock(),
        rag_graph=AsyncMock(),
        draft_graph=AsyncMock(),
        routing_graph=AsyncMock(),
        fast_llm_client=fake_fast_llm,
        checkpointer=MemorySaver(),
    )


@pytest.mark.asyncio
async def test_an_oversized_summary_and_backlog_do_not_silently_overflow(
    fake_llm, fake_fast_llm
):
    fake_llm.stream_chunks = ["merhaba, size nasıl yardımcı olabilirim?"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "context-budget-assist"}}

    # Far larger than anything a real turn could produce: the summarizer
    # caps itself at ~120 words, and HISTORY_RAW_CAP caps the backlog at 40
    # turns -- these are deliberately outside both to force the budget to
    # actually engage rather than pass through untouched.
    huge_summary = "Bu konuşmanın özetinde geçen bir cümle. " * 2000
    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Tur {i} için örnek mesaj metni."}
        for i in range(40)
    ]
    await graph.aupdate_state(
        config, {"history_summary": huge_summary, "history": long_history}
    )

    result = await graph.ainvoke({"input_text": "Merhaba", "document_id": None}, config=config)

    assert result["final_output"]["status"] != "FAILED"
    assert result["final_output"]["assist"]["status"] != "FAILED"

    sent_messages = fake_llm.stream_calls[-1]["messages"]
    system_message = next(m["content"] for m in sent_messages if m["role"] == "system")
    assert len(system_message) < len(huge_summary)

    conversational_turns = [m for m in sent_messages if m["role"] in ("user", "assistant")]
    # Bounded below the full seeded backlog (40) plus this turn's own message.
    assert len(conversational_turns) < len(long_history) + 1


@pytest.mark.asyncio
async def test_context_usage_is_reported_against_the_providers_window(
    fake_llm, fake_fast_llm
):
    """`details.context_usage.total`, aktif sağlayıcının bağlam penceresidir
    (Ollama'da OLLAMA_NUM_CTX, Evren'de EVREN_NUM_CTX) -- sabit değil."""
    fake_llm.stream_chunks = ["kısa yanıt"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "context-usage-total"}}

    result = await graph.ainvoke(
        {"input_text": "Bana bu sistemde neler yapabileceğimi anlatır mısın", "document_id": None},
        config=config,
    )

    usage = result["final_output"]["context_usage"]
    assert usage["total"] == fake_llm.context_window
    assert usage["used"] + usage["free"] == usage["total"]
    assert {segment["key"] for segment in usage["segments"]} >= {"system", "input", "reserved"}


@pytest.mark.asyncio
async def test_a_compacted_marker_shrinks_the_verbatim_window(fake_llm, fake_fast_llm):
    """``history_summarized_through`` ilerlemişse (kullanıcı sohbeti sıkıştırdı)
    o turlar artık modele birebir gönderilmez -- yalnızca özet olarak yaşar."""
    fake_llm.stream_chunks = ["tamam"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "context-budget-compacted"}}

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Tur {i} mesajı"}
        for i in range(10)
    ]
    await graph.aupdate_state(
        config,
        {"history": history, "history_summary": "eski özet", "history_summarized_through": 8},
    )

    await graph.ainvoke(
        {"input_text": "Son duruma göre devam edelim", "document_id": None}, config=config
    )

    sent_messages = fake_llm.stream_calls[-1]["messages"]
    conversational_turns = [m for m in sent_messages if m["role"] in ("user", "assistant")]
    # 8 tur özete katlandı; en fazla son 2 birebir tur + bu turun mesajı.
    assert len(conversational_turns) <= 3
    usage = (await graph.aget_state(config)).values["final_output"].get("context_usage")
    assert usage is not None


@pytest.mark.asyncio
async def test_a_wider_provider_window_grows_the_budget(fake_llm, fake_fast_llm, monkeypatch):
    """Evren'in penceresine geçince bağlam bütçesi (available) buna göre büyür."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "OLLAMA_NUM_CTX", settings.EVREN_NUM_CTX)
    fake_llm.stream_chunks = ["kısa yanıt"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "context-usage-wide"}}

    result = await graph.ainvoke(
        {"input_text": "Bana bu sistemde neler yapabileceğimi anlatır mısın", "document_id": None},
        config=config,
    )

    usage = result["final_output"]["context_usage"]
    assert usage["total"] == settings.EVREN_NUM_CTX
    assert usage["free"] > 200_000
