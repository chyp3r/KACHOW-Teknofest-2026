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
