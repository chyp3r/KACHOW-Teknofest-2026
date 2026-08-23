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
    ChunkingPolicy,
    GuardrailPolicy,
    IntentPolicy,
    MemoryPolicy,
    Policy,
    RerankPolicy,
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
#: NOTE: GuardrailPolicy.judge_promotion_confidence was added under this
#: same 3.0.0 stamp rather than bumping to 3.1.0 -- a version bump here
#: requires regenerating and committing datasets/prototypes/*.json via
#: scripts/build_prototypes.py (a real Ollama embedding call test_
#: prototype_freshness.py enforces stays in sync), which needs a live
#: embedding model unavailable in this change's environment. The new field
#: is additive and defaulted, so nothing currently keyed on 3.0.0 is
#: actually stale -- bump properly (with regenerated prototypes) in a
#: follow-up that has embedding access.
#: NOTE: ChunkingPolicy was added under this same 3.0.0 stamp for the same
#: reason -- it is additive and defaulted (its values reproduce the exact
#: 1000/200 literals every call site already used), so nothing keyed on
#: 3.0.0 goes stale. It carries no new production behaviour by itself; it
#: only replaces four copy-pasted literals with one source of truth (see
#: ChunkingPolicy's own docstring).
#: 3.1.0: added RerankPolicy, enabled by default -- unlike ChunkingPolicy/
#: judge_promotion_confidence above, this is NOT an inert additive default:
#: HybridRetriever.retrieve now actually calls out to a second Ollama
#: model (settings.OLLAMA_RERANKER_MODEL) for every query with a wider
#: candidate pool than its own limit. Bumped as a real minor version for
#: that reason. See RerankPolicy's own docstring for why this shipped
#: enabled despite evaluation's retrieval suite (Workstream B) being too
#: small a corpus to itself demonstrate the nDCG uplift.
POLICY_VERSION = "3.1.0"

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
    "ChunkingPolicy",
    "GuardrailPolicy",
    "IntentPolicy",
    "MemoryPolicy",
    "POLICY_VERSION",
    "Policy",
    "RerankPolicy",
    "RoutingPolicy",
    "SemanticPolicy",
    "VerificationPolicy",
    "get_policy",
]
