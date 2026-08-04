"""Budget-aware selection of verbatim conversation turns.

A separate mechanism from ``ContextBuilder``'s string blocks: conversation
history is injected into the assist agent as a list of role/content
messages (see ``AssistantAgent.run_stream``), not substituted into a single
prompt string, so it doesn't fit ``ContextBlock``'s ``render() -> str``
shape. Replaces the previous fixed ``HISTORY_WINDOW`` (always exactly 12
turns) with a window that shrinks when the rest of the prompt is already
large and grows when it isn't.
"""

from typing import Callable

from app.ai.policy import get_policy

_DEFAULT_MAX_TURNS = get_policy().memory.history_window


def select_history_window(
    history: list[dict[str, str]],
    remaining_budget_tokens: int,
    count_tokens: Callable[[str], int],
    min_turns: int = 2,
    max_turns: int | None = None,
) -> list[dict[str, str]]:
    """Pick the most recent turns that fit the remaining budget.

    Greedy from the most recent turn backwards -- recency is what pronoun/
    ellipsis resolution needs (see the module this replaced), so a turn that
    doesn't fit is one to drop, not one to truncate mid-message.

    Args:
        history: Prior turns, oldest first.
        remaining_budget_tokens: Tokens left for history after every other
            block in the same prompt has been accounted for.
        count_tokens: The active client's token estimator.
        min_turns: Always include at least this many recent turns (or fewer
            if `history` itself is shorter), even if that exceeds the
            budget -- a very tight budget should degrade the prompt, not
            make the assistant amnesiac after every single reply.
        max_turns: Cap on how many recent turns to consider at all, before
            budget is even applied. Defaults to `MemoryPolicy.history_window`
            (today's fixed value), so a generous budget still doesn't pull
            in the entire retained backlog.

    Returns:
        The selected turns, oldest first.
    """
    cap = max_turns if max_turns is not None else _DEFAULT_MAX_TURNS
    candidates = history[-cap:] if cap > 0 else []

    selected: list[dict[str, str]] = []
    spent = 0
    for turn in reversed(candidates):
        cost = count_tokens(turn.get("content", "") or "")
        if spent + cost > remaining_budget_tokens and len(selected) >= min_turns:
            break
        selected.append(turn)
        spent += cost

    selected.reverse()
    return selected
