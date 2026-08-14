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
    GuardrailPolicy,
    IntentPolicy,
    MemoryPolicy,
    Policy,
    RoutingPolicy,
    SemanticPolicy,
    VerificationPolicy,
)

#: Semantic version of the parameter set. Bump on any value change:
#: patch for a threshold, minor for a new parameter, major for a removed one.
#: 2.0.0: removed RoutingPolicy.units/human_approval_unit -- units are now a
#: runtime-managed domain (see app.domains.units), not a policy parameter.
#: 3.0.0: removed VerificationPolicy.unsupported_claim_penalty/
#: max_unsupported_penalty/judge_deterministic_weight/judge_model_weight --
#: penalty values now live in the single rule table at
#: app.ai.verification.confidence_rules.RULES, and the judge no longer
#: contributes a blended numeric score (see that module's docstring).
POLICY_VERSION = "3.0.0"

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
    "GuardrailPolicy",
    "IntentPolicy",
    "MemoryPolicy",
    "POLICY_VERSION",
    "Policy",
    "RoutingPolicy",
    "SemanticPolicy",
    "VerificationPolicy",
    "get_policy",
]
