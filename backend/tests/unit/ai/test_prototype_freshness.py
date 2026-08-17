"""Guards the committed prototype vectors against silently going stale.

``PrototypeMatcher._load`` (see ``app.ai.semantic.prototype_matcher``) refuses
to load a vector file whose ``model``/``policy_version`` stamp doesn't match
the running configuration -- correctly, deciding from stale vectors is worse
than paying for a model call. But that refusal is *silent* to anyone who
doesn't read the logs: the semantic rung just disappears from the ladder and
every lexically-abstained message falls straight through to the
clarify/guess fallback.

This is exactly what happened in production: ``datasets/prototypes/intent.json``
was stamped ``policy_version: "1.2.0"`` with labels
``["analyze", "chat", "document_qa", "draft"]`` while the running policy was
``1.4.0`` with intents ``draft/analyze/assist/revise`` -- the semantic layer
had been dead for weeks. This test is the guard against that recurring: it
fails the moment the committed file and the running policy drift apart,
instead of waiting for someone to notice degraded routing.
"""

import json
from pathlib import Path

import pytest

from app.ai.policy import POLICY_VERSION
from app.ai.workflows.planner import PLAN_BY_INTENT
from app.ai.semantic.prototype_matcher import PROTOTYPE_DIR
from app.core.config import settings

#: Mirrors app.ai.policy.prototypes.FAMILIES without importing it, so this
#: test also catches a family being added there but never rebuilt on disk.
from app.ai.policy.prototypes import FAMILIES

#: `clarify` is resolved without ever reaching the semantic rung (see
#: `resolve_plan`'s clarify-before-model branch), so it has no prototypes and
#: never will. `refuse` is not part of the intent space the semantic/fusion
#: layer classifies over at all -- it is a domain-admission verdict applied
#: *after* an intent (draft/analyze/assist/revise) is already resolved (see
#: `app.ai.workflows.scope.resolve_scope` and `planner._apply_scope_gate`),
#: so it likewise has no prototypes and never will. `transfer` (Faz 4, #201)
#: is not a resolvable intent at all -- it is a tool the assist step's model
#: may call mid-conversation (`app.ai.tools.transfer_tools`), so it was never
#: a candidate for this table in the first place. (An isolated semantic gate
#: for an earlier, since-removed deterministic `transfer` intent was
#: prototyped and reverted after measurement against real embeddings; see
#: `git log` on this file for that finding.)
_EXPECTED_INTENT_LABELS = set(PLAN_BY_INTENT) - {"clarify", "refuse"}


def _load(family: str) -> dict:
    path = Path(PROTOTYPE_DIR) / f"{family}.json"
    if not path.exists():
        pytest.fail(
            f"{path} is missing. Run: "
            "docker compose run --rm --no-deps backend python scripts/build_prototypes.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("family", FAMILIES)
def test_prototype_file_matches_running_policy(family: str) -> None:
    payload = _load(family)

    assert payload.get("policy_version") == POLICY_VERSION, (
        f"datasets/prototypes/{family}.json was built under policy "
        f"{payload.get('policy_version')!r} but {POLICY_VERSION!r} is active -- "
        "the semantic layer has silently disabled itself. Rerun "
        "scripts/build_prototypes.py and commit the result."
    )
    assert payload.get("model") == settings.OLLAMA_EMBEDDING_MODEL, (
        f"datasets/prototypes/{family}.json was embedded with "
        f"{payload.get('model')!r} but {settings.OLLAMA_EMBEDDING_MODEL!r} is "
        "configured -- rerun scripts/build_prototypes.py."
    )


def test_intent_prototypes_cover_every_semantic_intent() -> None:
    payload = _load("intent")
    labels = {entry["label"] for entry in payload.get("prototypes", [])}

    assert labels == _EXPECTED_INTENT_LABELS, (
        f"datasets/prototypes/intent.json covers {sorted(labels)} but the "
        f"active intent space is {sorted(_EXPECTED_INTENT_LABELS)} -- an "
        "intent with no prototypes can never be resolved by the semantic "
        "rung, only guessed or asked about."
    )
