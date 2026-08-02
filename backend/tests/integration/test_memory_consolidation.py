"""End-to-end test for the rolling conversation-summary consolidation.

Exercises the actual compiled planning graph across many chat turns on the
same thread, with only the LLM-backed sub-graphs (document analysis, RAG,
drafting, routing -- none of which a chat-intent turn touches) replaced by
mocks, following the same pattern as test_hitl_flow.py. Uses MemorySaver
rather than AsyncPostgresSaver so this runs without a database, in CI.

Verifies consolidate_memory_node only fires once a worth-while batch of
turns has aged out of the verbatim HISTORY_WINDOW, not on every single turn.
"""

from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.ai.workflows.planning_graph import create_planning_graph


def _build_graph(fake_llm, fake_fast_llm):
    """Mirrors test_hitl_flow.py's _build_graph -- sub-graphs are mocked
    since a chat-intent turn never invokes them; only chat_agent (fake_llm)
    and the memory summarizer (fake_fast_llm) are exercised."""
    graph = create_planning_graph(
        llm_client=fake_llm,
        document_analysis_graph=AsyncMock(),
        rag_graph=AsyncMock(),
        draft_graph=AsyncMock(),
        routing_graph=AsyncMock(),
        fast_llm_client=fake_fast_llm,
        checkpointer=MemorySaver(),
    )
    return graph


@pytest.mark.asyncio
async def test_a_chat_turn_persists_both_the_user_message_and_the_reply(
    fake_llm, fake_fast_llm
):
    """Regression: execute_step_node used to nest chat_result's own "history"
    entry (the assistant's reply) inside updates["chat_result"] without ever
    hoisting it to a top-level update, so the history reducer never saw it --
    assistant turns silently never reached checkpointed memory, only user
    turns did."""
    fake_llm.stream_chunks = ["merhaba, size nasıl yardımcı olabilirim?"]
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "memory-consolidation-0"}}

    await graph.ainvoke({"input_text": "Merhaba", "document_id": None}, config=config)

    snapshot = await graph.aget_state(config)
    history = snapshot.values["history"]
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "Merhaba"}
    assert history[1] == {
        "role": "assistant",
        "content": "merhaba, size nasıl yardımcı olabilirim?",
    }


@pytest.mark.asyncio
async def test_summary_stays_empty_until_enough_turns_overflow_the_window(
    fake_llm, fake_fast_llm
):
    fake_llm.stream_chunks = ["ok"]
    fake_fast_llm.generate_return = "Özet metni."
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "memory-consolidation-1"}}

    # 7 turns -> 14 history entries -> 2 overflowed past HISTORY_WINDOW=12,
    # below CONSOLIDATION_BATCH_SIZE=4 -- must not fire yet.
    for i in range(7):
        await graph.ainvoke(
            {"input_text": f"Mesaj {i}", "document_id": None}, config=config
        )

    snapshot = await graph.aget_state(config)
    assert not snapshot.values.get("history_summary")
    assert snapshot.values.get("history_summarized_through", 0) == 0
    assert fake_fast_llm.generate_calls == []


@pytest.mark.asyncio
async def test_summary_populates_once_the_batch_threshold_is_crossed(
    fake_llm, fake_fast_llm
):
    fake_llm.stream_chunks = ["ok"]
    fake_fast_llm.generate_return = "Özet metni."
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "memory-consolidation-2"}}

    # 8 turns -> 16 history entries -> 4 overflowed, meets batch_size=4.
    for i in range(8):
        await graph.ainvoke(
            {"input_text": f"Mesaj {i}", "document_id": None}, config=config
        )

    snapshot = await graph.aget_state(config)
    assert snapshot.values["history_summary"] == "Özet metni."
    assert snapshot.values["history_summarized_through"] == 4
    # Fired exactly once across 8 turns, not once per turn.
    assert len(fake_fast_llm.generate_calls) == 1


@pytest.mark.asyncio
async def test_consolidation_does_not_shrink_the_verbatim_window_sent_to_chat(
    fake_llm, fake_fast_llm
):
    """The prompt-size regression this guards against: raising the raw
    retention cap must never grow the number of verbatim turns sent to the
    chat agent beyond HISTORY_WINDOW."""
    from app.ai.workflows.planning_graph import HISTORY_WINDOW

    fake_llm.stream_chunks = ["ok"]
    fake_fast_llm.generate_return = "Özet metni."
    graph = _build_graph(fake_llm, fake_fast_llm)
    config = {"configurable": {"thread_id": "memory-consolidation-3"}}

    for i in range(10):
        await graph.ainvoke(
            {"input_text": f"Mesaj {i}", "document_id": None}, config=config
        )

    last_call_messages = fake_llm.stream_calls[-1]["messages"]
    # BaseAgent.stream prepends one system message to the prior-turns window
    # plus the current user turn, so the cap is HISTORY_WINDOW + 2, not
    # HISTORY_WINDOW -- this only guards against the window itself growing
    # unbounded (the raw-cap change must not have touched HISTORY_WINDOW).
    assert len(last_call_messages) <= HISTORY_WINDOW + 2
