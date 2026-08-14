"""Guards the parameter invariants and the aliases that read them.

Collecting the thresholds into one module is only half the point; the other half
is that relationships between them can now be asserted. Two of these were
previously true by coincidence and nothing would have caught their violation:

* The routing threshold sits below the automation threshold. They are the same
  concept at different severities -- 70 is "may be sent without review", 50 is
  "may not be routed at all" -- and inverting them would make a draft too weak
  to route simultaneously good enough to send.
* Every configured node budget is actually consumed by a node. `writer` and
  `judge` sat in that table unread for their entire existence, which meant the
  most expensive step in the draft budget had no protection while appearing to
  have one.

The alias tests exist because every consuming module keeps its module-level
name (`MIN_AUTOMATED_CONFIDENCE_SCORE` and friends) derived from the policy. If
one were ever re-hardcoded, imports would still work and only the drift would
show -- which is exactly what these assert.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from app.ai.policy import POLICY_VERSION, Policy, get_policy
from app.ai.policy.budget import node_budget
from app.ai.reasoning_levels import get_reasoning_level_preset
from app.ai.verification import draft_verifier, llm_judge
from app.ai.workflows import intent_scorer, planning_graph, routing_graph
from app.core.enums.reasoning_level import ReasoningLevel

WORKFLOW_DIR = Path(draft_verifier.__file__).resolve().parents[1] / "workflows"


def test_policy_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", POLICY_VERSION)


def test_the_shipped_policy_satisfies_every_invariant():
    get_policy().check_invariants()


def test_the_routing_threshold_stays_below_the_automation_threshold():
    policy = get_policy()

    assert (
        policy.routing.human_approval_score_threshold
        < policy.verification.min_automated_confidence
    )


def test_inverting_the_two_approval_thresholds_is_rejected():
    policy = get_policy()
    broken = replace(
        policy,
        routing=replace(policy.routing, human_approval_score_threshold=95.0),
    )

    with pytest.raises(ValueError, match="human_approval_score_threshold"):
        broken.check_invariants()


def test_compound_floor_cannot_sit_below_the_presence_floor():
    """A compound reading cannot need less evidence than a single one."""
    policy = get_policy()
    broken = replace(policy, intent=replace(policy.intent, compound_floor=0.1))

    with pytest.raises(ValueError, match="compound_floor"):
        broken.check_invariants()


def test_raw_history_cap_must_exceed_the_verbatim_window():
    """Otherwise consolidation never has overflow to fold into the summary."""
    policy = get_policy()
    broken = replace(policy, memory=replace(policy.memory, history_raw_cap=4))

    with pytest.raises(ValueError, match="history_raw_cap"):
        broken.check_invariants()


def test_a_node_budget_above_the_workflow_ceiling_is_rejected():
    policy = get_policy()
    broken = replace(
        policy,
        budget=replace(policy.budget, node_seconds={"analyze": 9999.0}),
    )

    with pytest.raises(ValueError, match="ceiling"):
        broken.check_invariants()


def test_every_configured_node_budget_is_consumed_by_a_node():
    """The regression this module exists for.

    `NODE_TIMEOUT_SECONDS` carried `writer: 120.0` and `judge: 20.0` that no
    call site ever read -- `draft_graph.py` did not even import `node_timeout`.
    A budget nobody applies is worse than no budget, because it reads as
    protection that is not there.
    """
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in WORKFLOW_DIR.glob("*.py")
    )

    unread = [
        node
        for node in get_policy().budget.node_seconds
        if f'node_timeout("{node}")' not in sources
        and f'node_budget("{node}"' not in sources
    ]

    assert unread == [], f"budgets configured but never applied: {unread}"


@pytest.mark.parametrize(
    "level, multiplier",
    [
        (ReasoningLevel.FAST, 0.6),
        (ReasoningLevel.BALANCED, 1.0),
        (ReasoningLevel.DEEP, 1.8),
    ],
)
def test_node_budget_scales_with_the_reasoning_level(level, multiplier):
    base = get_policy().budget.node_seconds["analyze"]

    assert node_budget("analyze", level) == pytest.approx(base * multiplier)
    assert get_reasoning_level_preset(level).timeout_multiplier == multiplier


def test_no_level_makes_any_node_budget_tighter_than_balanced_for_deep():
    """`deep` buys wall clock; it must never spend less of it on a node."""
    for node in get_policy().budget.node_seconds:
        assert node_budget(node, ReasoningLevel.DEEP) >= node_budget(
            node, ReasoningLevel.BALANCED
        )


def test_node_budget_is_clamped_to_the_workflow_ceiling():
    ceiling = get_policy().budget.workflow_ceiling_seconds

    for node in get_policy().budget.node_seconds:
        assert node_budget(node, ReasoningLevel.DEEP) <= ceiling


def test_an_unknown_node_falls_back_to_the_ceiling_not_to_zero():
    """A missing key must be a no-op timeout, never an instant one."""
    assert node_budget("no-such-node") == get_policy().budget.workflow_ceiling_seconds


def test_a_malformed_reasoning_level_resolves_to_balanced():
    """Levels arrive from checkpointed state; an old value must not raise."""
    balanced = node_budget("analyze", ReasoningLevel.BALANCED)

    assert node_budget("analyze", "not-a-level") == balanced
    assert node_budget("analyze", None) == balanced


def test_consuming_modules_read_their_constants_from_the_policy():
    policy = get_policy()

    assert draft_verifier.MIN_AUTOMATED_CONFIDENCE_SCORE == policy.verification.min_automated_confidence
    assert draft_verifier.TOKEN_OVERLAP_THRESHOLD == policy.verification.token_overlap_threshold
    assert llm_judge._ECHO_OVERLAP_THRESHOLD == policy.verification.judge_echo_overlap_threshold
    assert routing_graph.HUMAN_APPROVAL_SCORE_THRESHOLD == policy.routing.human_approval_score_threshold
    assert intent_scorer.DECISIVE_MARGIN == policy.intent.decisive_margin
    assert intent_scorer.PRESENCE_FLOOR == policy.intent.presence_floor
    assert intent_scorer.COMPOUND_FLOOR == policy.intent.compound_floor
    assert planning_graph.HISTORY_WINDOW == policy.memory.history_window
    assert planning_graph.HISTORY_RAW_CAP == policy.memory.history_raw_cap
    assert planning_graph.CONSOLIDATION_BATCH_SIZE == policy.memory.consolidation_batch_size
    assert planning_graph.QA_RESULT_LIMIT == policy.memory.qa_result_limit


def test_the_policy_is_a_single_frozen_instance():
    """No setter, no reload: a threshold change is a code change."""
    assert get_policy() is get_policy()

    with pytest.raises(Exception):
        get_policy().verification.min_automated_confidence = 1.0  # type: ignore[misc]


def test_a_policy_can_be_constructed_without_arguments():
    """Every field carries its own default, so the schema is self-describing."""
    Policy(version="0.0.0").check_invariants()
