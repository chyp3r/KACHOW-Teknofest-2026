"""Single access point for the deterministic decision layer's parameters.

``get_policy()`` returns one frozen instance for the process. There is no
setter and no reload: a threshold change is a code change with a CHANGELOG
entry and an eval run behind it, which is the whole reason this is Python and
not a config file.

``POLICY_VERSION`` is bumped whenever a value changes. It is stamped onto the
evaluation reports and exported as a Prometheus label so a shift in a production
metric can be attributed to the policy it was produced under, rather than being
mistaken for a change in the traffic.
"""

from app.ai.policy.schema import (
    BudgetPolicy,
    IntentPolicy,
    MemoryPolicy,
    Policy,
    RoutingPolicy,
    VerificationPolicy,
)

#: Semantic version of the parameter set. Bump on any value change:
#: patch for a threshold, minor for a new parameter, major for a removed one.
POLICY_VERSION = "1.0.0"

_POLICY = Policy(version=POLICY_VERSION)

# Fails the process at import rather than letting a self-contradicting policy
# produce quietly wrong decisions -- an inverted approval threshold would make a
# draft too weak to route simultaneously good enough to send.
_POLICY.check_invariants()


def get_policy() -> Policy:
    """Return the active policy.

    Returns:
        The process-wide frozen policy instance.
    """
    return _POLICY


__all__ = [
    "BudgetPolicy",
    "IntentPolicy",
    "MemoryPolicy",
    "POLICY_VERSION",
    "Policy",
    "RoutingPolicy",
    "VerificationPolicy",
    "get_policy",
]
