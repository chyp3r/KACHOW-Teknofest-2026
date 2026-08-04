"""Unit tests for budget-aware conversation-turn selection."""

from app.ai.context.history import select_history_window


def _turns(n: int) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"mesaj {i}"} for i in range(n)]


def _count_chars(text: str) -> int:
    """A trivial, deterministic estimator: cost == character count."""
    return len(text)


def test_everything_fits_when_the_budget_is_generous():
    history = _turns(5)

    selected = select_history_window(history, remaining_budget_tokens=10_000, count_tokens=_count_chars)

    assert selected == history


def test_oldest_turns_drop_first_when_the_budget_is_tight():
    history = _turns(10)
    # Each "mesaj N" costs ~8 chars; budget for ~3 turns plus min_turns floor.
    selected = select_history_window(
        history, remaining_budget_tokens=24, count_tokens=_count_chars, min_turns=1
    )

    assert selected == history[-len(selected):]
    assert len(selected) < len(history)


def test_min_turns_is_respected_even_over_budget():
    history = _turns(5)

    selected = select_history_window(
        history, remaining_budget_tokens=0, count_tokens=_count_chars, min_turns=2
    )

    assert selected == history[-2:]


def test_max_turns_caps_the_candidate_pool_before_budgeting():
    history = _turns(20)

    selected = select_history_window(
        history,
        remaining_budget_tokens=10_000,
        count_tokens=_count_chars,
        min_turns=1,
        max_turns=3,
    )

    assert selected == history[-3:]


def test_empty_history_returns_empty():
    assert select_history_window([], remaining_budget_tokens=100, count_tokens=_count_chars) == []
