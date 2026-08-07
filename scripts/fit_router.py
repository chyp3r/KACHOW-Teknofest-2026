"""Fits the router's fusion weights and writes them to app/ai/policy/router_weights.py.

Run after editing the training-relevant slice of the gold set
(``evaluation/datasets/intents.jsonl``), the feature set
(``app.ai.workflows.router_features``), or ``POLICY_VERSION``:

    docker compose run --rm --no-deps backend python scripts/fit_router.py

Same reasoning as ``scripts/build_prototypes.py``: fitting is cheap and
reproducible enough to do at request time, but doing it there would make
every planning turn pay for a training pass over the gold set. Fit once,
freeze the coefficients into a checked-in module, and the runtime path
(``app.ai.workflows.router_fusion.predict_proba``) is pure arithmetic over a
handful of floats.

Training excludes four categories on purpose:

* ``compound`` -- resolved by the additive lexical-score check in
  ``resolve_plan`` *before* fusion runs at all (see its docstring). A softmax
  is a competition between classes by construction; forcing a single label
  onto a message that is genuinely both ``draft`` and ``analyze`` would teach
  the model to suppress exactly the "both score high independently" signal
  the compound check depends on.
* ``clarify_resolution`` -- these messages ("Evet", "Tamam") are resolved by
  ``_try_resolve_pending_clarification`` before the ladder runs at all; they
  are not representative fusion inputs and would teach the model that a bare
  "Evet" means ``draft`` unconditionally.
* ``escalation`` -- ``expected_abstain: true`` cases have no single-label
  gold answer to train against.
* ``heldout_paraphrase`` -- held out from every layer's *tuning* by design
  (see the gold set's own header note); this is the set the eval report's
  headline number is measured against, and training on it would make that
  number meaningless.

A 5-fold cross-validation pass reports the expected out-of-fold accuracy
before the final weights (fit on the full training slice) are written --
the number worth reading is the CV one, not the training accuracy, which
this small a model will always overfit toward.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.policy import POLICY_VERSION  # noqa: E402
from app.ai.semantic.prototype_matcher import PrototypeMatcher  # noqa: E402
from app.ai.workflows.intent_scorer import score_intents  # noqa: E402
from app.ai.workflows.router_features import (  # noqa: E402
    FEATURE_NAMES,
    RouterSignals,
    extract_features,
)
from app.ai.workflows.router_fusion import INTENTS, softmax  # noqa: E402
from evaluation.harness.cached_embeddings import CachedEmbeddingsClient  # noqa: E402
from evaluation.harness.runner import EvalCase, load_cases  # noqa: E402

#: `app` lives at `backend/app` on the host but is mounted straight to
#: `/workspace/app` in the container (see compose.yml) -- resolving via
#: the already-imported `app` package, the same trick `scripts/
#: build_prototypes.py`'s `PROTOTYPE_DIR` sidesteps by using `settings.
#: PROTOTYPE_DIR` instead, works in both places without hardcoding either
#: layout.
import app as _app_package  # noqa: E402

OUTPUT_PATH = Path(_app_package.__file__).resolve().parent / "ai" / "policy" / "router_weights.py"

_DOCUMENT_PLACEHOLDER = "uploads/evrak_gold.pdf"

#: See module docstring for why each is excluded.
_EXCLUDED_CATEGORIES = frozenset(
    {"compound", "clarify_resolution", "escalation", "heldout_paraphrase"}
)

LEARNING_RATE = 0.15
EPOCHS = 3000
L2_LAMBDA = 0.02
FOLDS = 5

Row = tuple[str, dict[str, float], str]


def _build_matcher() -> Optional[PrototypeMatcher]:
    try:
        client = CachedEmbeddingsClient()
    except FileNotFoundError as exc:
        print(f"[fit_router] {exc} -- fitting without semantic features.")
        return None
    matcher = PrototypeMatcher(client, model_name=client.model)
    return matcher if matcher.available else None


def _training_case(case: EvalCase) -> bool:
    return case.category not in _EXCLUDED_CATEGORIES and case.expected.get("intent") in INTENTS


async def _build_rows() -> list[Row]:
    """Extract one feature vector per eligible gold-set case."""
    cases = [case for case in load_cases("intents") if _training_case(case)]
    matcher = _build_matcher()

    rows: list[Row] = []
    for case in cases:
        message = case.payload.get("message", "")
        document_id = _DOCUMENT_PLACEHOLDER if case.payload.get("document_attached") else None
        has_active_draft = bool(case.payload.get("active_draft"))
        previous_intent = case.payload.get("previous_intent")

        lexical = score_intents(message, document_id, previous_intent, has_active_draft)
        semantic = (
            await matcher.label_similarities(message, "intent") if matcher is not None else None
        )
        signals = RouterSignals(
            lexical=lexical,
            semantic=semantic,
            has_document=document_id is not None,
            has_active_draft=has_active_draft,
            previous_intent=previous_intent,
        )
        features = extract_features(message, signals)
        rows.append((case.id, features, case.expected["intent"]))

    return rows


def _predict(
    features: dict[str, float],
    weights: dict[str, dict[str, float]],
    bias: dict[str, float],
) -> dict[str, float]:
    logits = {
        intent: bias[intent]
        + sum(weights[intent][name] * features[name] for name in FEATURE_NAMES)
        for intent in INTENTS
    }
    return softmax(logits)


def _fit(rows: list[Row]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Full-batch gradient descent on cross-entropy loss with L2 regularisation.

    Deterministic on purpose: zero-initialised weights on a convex objective
    (softmax regression's loss is convex in its parameters for fixed features)
    need no random restarts to reach the same optimum every run -- worth
    keeping, since a training script whose output changes between runs on
    unchanged input would make the checked-in weights impossible to review.
    """
    weights = {intent: {name: 0.0 for name in FEATURE_NAMES} for intent in INTENTS}
    bias = {intent: 0.0 for intent in INTENTS}
    n = len(rows)

    for _epoch in range(EPOCHS):
        grad_w = {intent: {name: 0.0 for name in FEATURE_NAMES} for intent in INTENTS}
        grad_b = {intent: 0.0 for intent in INTENTS}

        for _case_id, features, label in rows:
            probs = _predict(features, weights, bias)
            for intent in INTENTS:
                error = probs[intent] - (1.0 if intent == label else 0.0)
                grad_b[intent] += error
                for name in FEATURE_NAMES:
                    grad_w[intent][name] += error * features[name]

        for intent in INTENTS:
            bias[intent] -= LEARNING_RATE * grad_b[intent] / n
            for name in FEATURE_NAMES:
                regularised = grad_w[intent][name] / n + L2_LAMBDA * weights[intent][name]
                weights[intent][name] -= LEARNING_RATE * regularised

    return weights, bias


def _cross_validate(rows: list[Row]) -> float:
    """5-fold CV accuracy, folds assigned by position so every class-block
    (the gold set is grouped by category, hence roughly by label) spreads
    across every fold instead of concentrating in one.
    """
    correct = 0
    for fold in range(FOLDS):
        train = [row for index, row in enumerate(rows) if index % FOLDS != fold]
        held_out = [row for index, row in enumerate(rows) if index % FOLDS == fold]
        if not train or not held_out:
            continue
        weights, bias = _fit(train)
        for _case_id, features, label in held_out:
            probs = _predict(features, weights, bias)
            predicted = max(probs.items(), key=lambda item: item[1])[0]
            if predicted == label:
                correct += 1
    return correct / len(rows) if rows else 0.0


def _render(
    weights: dict[str, dict[str, float]], bias: dict[str, float], *, cv_accuracy: float, n_rows: int
) -> str:
    def _mapping(values: dict[str, float]) -> str:
        items = ",\n".join(f'            "{key}": {value:.6f}' for key, value in values.items())
        return "MappingProxyType(\n" + "        {\n" + items + ",\n        }\n    )"

    coefficients_body = ",\n".join(
        f'        "{intent}": {_mapping(weights[intent])}' for intent in INTENTS
    )
    bias_body = ",\n".join(f'        "{intent}": {bias[intent]:.6f}' for intent in INTENTS)
    feature_names_body = ",\n".join(f'    "{name}"' for name in FEATURE_NAMES)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return f'''"""Fitted coefficients for the router's calibrated fusion layer.

GENERATED FILE -- do not hand-edit. Produced by ``scripts/fit_router.py`` from
``evaluation/datasets/intents.jsonl``. Rerun that script (and commit the
result) after changing the training-relevant slice of the gold set, the
feature set in ``app.ai.workflows.router_features``, or ``POLICY_VERSION``.

Fitted {generated_at} against {n_rows} training rows (see
``scripts/fit_router.py``'s module docstring for which gold-set categories
are excluded and why). 5-fold cross-validation accuracy at fit time:
{cv_accuracy:.4f} -- the number to compare a refit against, not training
accuracy, which a model this size will always overfit toward on a few
hundred rows.
"""

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.ai.policy import POLICY_VERSION
from app.ai.workflows.router_features import FEATURE_NAMES
from app.ai.workflows.router_fusion import INTENTS

logger = logging.getLogger(__name__)

__all__ = ["RouterWeights", "ROUTER_WEIGHTS"]


@dataclass(frozen=True)
class RouterWeights:
    """The fusion layer's fitted linear coefficients, one set per intent.

    Attributes:
        version: The ``POLICY_VERSION`` this fit was produced under. Checked
            against the running policy below (a warning, not a hard failure --
            unlike a stale semantic-prototype file, there is no fallback state
            for the router to degrade to if these coefficients were refused:
            fusion *is* the decision mechanism now, not an optional layer a
            missing file can simply skip).
        feature_names: The exact feature order these coefficients were fit
            against. Validated against ``router_features.FEATURE_NAMES`` at
            import time -- a genuine structural mismatch here, unlike a stale
            version stamp, would make every score silently wrong, so this one
            *is* fatal.
        bias: Intent -> per-class bias term.
        coefficients: Intent -> feature name -> weight.
    """

    version: str
    feature_names: tuple[str, ...]
    bias: Mapping[str, float]
    coefficients: Mapping[str, Mapping[str, float]]

    def __post_init__(self) -> None:
        if self.feature_names != FEATURE_NAMES:
            raise ValueError(
                "RouterWeights.feature_names does not match the running "
                "router_features.FEATURE_NAMES -- rerun scripts/fit_router.py."
            )
        if set(self.bias) != set(INTENTS) or set(self.coefficients) != set(INTENTS):
            raise ValueError("RouterWeights must cover exactly router_fusion.INTENTS.")
        for intent in INTENTS:
            if set(self.coefficients[intent]) != set(FEATURE_NAMES):
                raise ValueError(
                    f"RouterWeights.coefficients[{{intent!r}}] does not cover every "
                    "feature in FEATURE_NAMES -- rerun scripts/fit_router.py."
                )


ROUTER_WEIGHTS = RouterWeights(
    version={POLICY_VERSION!r},
    feature_names=(
{feature_names_body}
    ),
    bias=MappingProxyType(
        {{
{bias_body}
        }}
    ),
    coefficients=MappingProxyType(
        {{
{coefficients_body}
        }}
    ),
)

if ROUTER_WEIGHTS.version != POLICY_VERSION:
    logger.warning(
        "Router fusion weights were fit under policy %s but %s is active -- "
        "scoring with a policy-stale (but structurally valid) model. Rerun "
        "scripts/fit_router.py.",
        ROUTER_WEIGHTS.version,
        POLICY_VERSION,
    )
'''


async def main() -> int:
    rows = await _build_rows()
    print(f"[fit_router] {len(rows)} eğitim satırı ({FEATURE_NAMES.__len__()} özellik).")

    cv_accuracy = _cross_validate(rows)
    print(f"[fit_router] {FOLDS}-katlı çapraz doğrulama doğruluğu: {cv_accuracy:.4f}")

    weights, bias = _fit(rows)

    train_correct = sum(
        1
        for _case_id, features, label in rows
        if max(_predict(features, weights, bias).items(), key=lambda item: item[1])[0] == label
    )
    print(f"[fit_router] Eğitim kümesi doğruluğu (aşırı öğrenmeye açık): {train_correct / len(rows):.4f}")

    OUTPUT_PATH.write_text(
        _render(weights, bias, cv_accuracy=cv_accuracy, n_rows=len(rows)), encoding="utf-8"
    )
    print(f"[fit_router] yazıldı: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
