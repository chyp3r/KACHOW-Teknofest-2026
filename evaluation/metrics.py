"""Classification and calibration metrics for the deterministic decision layer.

Deliberately dependency-free: only the standard library. The evaluation harness
runs inside the ``backend`` container, and pulling numpy/scikit-learn in for a
handful of counting loops over at most a few hundred cases would add a
dependency to the image for no measurable benefit (project rule 6).

The metrics that matter here are not the usual accuracy-only set. A decision
layer that can *abstain* -- hand a case up to the next layer instead of guessing
-- has two separate quality axes:

* how often it is right when it does decide (``accuracy``/``macro_f1`` over the
  decided subset), and
* whether it abstains on the cases it would have got wrong
  (``risk_coverage_curve``, ``expected_calibration_error``).

Optimising the first alone produces a layer that decides everything confidently
and wrongly; optimising the second alone produces one that abstains on
everything and pushes the entire load onto the model tier.
"""

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

__all__ = [
    "Prediction",
    "LabelScore",
    "RiskCoveragePoint",
    "BinaryRates",
    "accuracy",
    "abstention_rate",
    "confusion_matrix",
    "per_label_scores",
    "macro_f1",
    "risk_coverage_curve",
    "expected_calibration_error",
    "precision_at_k",
    "recall_at_k",
    "mean_reciprocal_rank",
    "hit_rate_at_k",
    "ndcg_at_k",
    "binary_rates",
]


@dataclass(frozen=True)
class Prediction:
    """One case's outcome, as every metric here consumes it.

    Attributes:
        expected: The gold label.
        predicted: The label the decision function produced, or None when it
            abstained.
        confidence: The decision function's own confidence in ``predicted``,
            in [0, 1]. Layers that report no confidence pass 1.0 for a decision
            and 0.0 for an abstention.
        abstained: Whether the decision function declined to decide. Kept
            explicit rather than inferred from ``predicted is None`` so a
            function that returns a label *and* flags low confidence can be
            measured both ways.
    """

    expected: str
    predicted: Optional[str] = None
    confidence: float = 0.0
    abstained: bool = False

    @property
    def correct(self) -> bool:
        """Whether a non-abstained prediction matched the gold label."""
        return not self.abstained and self.predicted == self.expected


@dataclass(frozen=True)
class LabelScore:
    """Precision, recall and F1 for a single label."""

    label: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True)
class RiskCoveragePoint:
    """One operating point on the risk-coverage curve.

    Attributes:
        threshold: The confidence cut-off this point corresponds to.
        coverage: Fraction of all cases decided at or above the threshold.
        risk: Error rate *within* the covered subset. Undefined (0.0) when
            coverage is zero.
    """

    threshold: float
    coverage: float
    risk: float


@dataclass(frozen=True)
class BinaryRates:
    """Confusion counts and rates for a yes/no decision."""

    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0

    @property
    def false_positive_rate(self) -> float:
        """Share of genuine negatives wrongly flagged positive."""
        denominator = self.false_positive + self.true_negative
        return self.false_positive / denominator if denominator else 0.0

    @property
    def false_negative_rate(self) -> float:
        """Share of genuine positives wrongly passed as negative."""
        denominator = self.false_negative + self.true_positive
        return self.false_negative / denominator if denominator else 0.0

    @property
    def accuracy(self) -> float:
        """Share of decisions that matched the gold answer."""
        total = (
            self.true_positive
            + self.false_positive
            + self.true_negative
            + self.false_negative
        )
        return (self.true_positive + self.true_negative) / total if total else 0.0


def _decided(predictions: Sequence[Prediction]) -> list[Prediction]:
    """Return only the predictions where the layer actually committed."""
    return [item for item in predictions if not item.abstained]


def accuracy(predictions: Sequence[Prediction], *, over_decided: bool = True) -> float:
    """Fraction of correct predictions.

    Args:
        predictions: The cases to score.
        over_decided: When True (the default) the denominator is the decided
            subset, which answers "when it commits, how often is it right?".
            When False the denominator is every case, so an abstention counts
            as an error -- which is what you want when comparing a layer
            against one that never abstains.

    Returns:
        The accuracy in [0, 1], or 0.0 when the denominator is empty.
    """
    population = _decided(predictions) if over_decided else list(predictions)
    if not population:
        return 0.0
    return sum(1 for item in population if item.correct) / len(population)


def abstention_rate(predictions: Sequence[Prediction]) -> float:
    """Fraction of cases handed up to the next layer instead of decided.

    Args:
        predictions: The cases to score.

    Returns:
        The abstention rate in [0, 1], or 0.0 for an empty input.
    """
    if not predictions:
        return 0.0
    return sum(1 for item in predictions if item.abstained) / len(predictions)


def confusion_matrix(predictions: Sequence[Prediction]) -> dict[str, dict[str, int]]:
    """Count gold-vs-predicted pairs.

    Abstentions are recorded under the predicted key ``"<abstain>"`` rather than
    dropped, so a matrix row still sums to that label's support.

    Args:
        predictions: The cases to score.

    Returns:
        ``matrix[expected][predicted] = count``.
    """
    matrix: dict[str, dict[str, int]] = {}
    for item in predictions:
        predicted = "<abstain>" if item.abstained else (item.predicted or "<none>")
        row = matrix.setdefault(item.expected, {})
        row[predicted] = row.get(predicted, 0) + 1
    return matrix


def per_label_scores(predictions: Sequence[Prediction]) -> list[LabelScore]:
    """Precision, recall and F1 for every gold label, sorted by label.

    An abstention counts against recall (the label was expected and not
    produced) but not against any other label's precision -- abstaining is not
    the same failure as confidently answering something else, and collapsing
    the two hides exactly the behaviour this harness exists to measure.

    Args:
        predictions: The cases to score.

    Returns:
        One :class:`LabelScore` per gold label.
    """
    labels = sorted({item.expected for item in predictions})
    scores: list[LabelScore] = []

    for label in labels:
        support = sum(1 for item in predictions if item.expected == label)
        true_positive = sum(
            1 for item in predictions if item.correct and item.expected == label
        )
        predicted_positive = sum(
            1 for item in predictions if not item.abstained and item.predicted == label
        )

        precision = true_positive / predicted_positive if predicted_positive else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        scores.append(
            LabelScore(
                label=label,
                precision=precision,
                recall=recall,
                f1=f1,
                support=support,
            )
        )
    return scores


def macro_f1(predictions: Sequence[Prediction]) -> float:
    """Unweighted mean of per-label F1.

    Macro rather than micro on purpose: the intent gold set is deliberately
    unbalanced (there are far more plausible ``chat`` messages than
    ``document_qa`` ones), and a micro average would let a layer score well by
    getting the majority label right while failing the rare ones the system
    actually depends on.

    Args:
        predictions: The cases to score.

    Returns:
        The macro F1 in [0, 1], or 0.0 for an empty input.
    """
    scores = per_label_scores(predictions)
    if not scores:
        return 0.0
    return sum(score.f1 for score in scores) / len(scores)


def risk_coverage_curve(
    predictions: Sequence[Prediction], *, thresholds: Optional[Sequence[float]] = None
) -> list[RiskCoveragePoint]:
    """Trace error rate against coverage as the confidence cut-off moves.

    This is the curve a confidence threshold gets calibrated on: the operating
    point wanted is the one where risk is acceptable and coverage is as high as
    it goes, and it is chosen from the middle of a flat region rather than the
    single best point (which is almost always noise on a set this size).

    Args:
        predictions: The cases to score.
        thresholds: Confidence cut-offs to evaluate. Defaults to 0.0..1.0 in
            steps of 0.05.

    Returns:
        One point per threshold, in ascending threshold order.
    """
    if thresholds is None:
        thresholds = [round(index * 0.05, 2) for index in range(21)]

    total = len(predictions)
    points: list[RiskCoveragePoint] = []

    for threshold in thresholds:
        covered = [
            item
            for item in predictions
            if not item.abstained and item.confidence >= threshold
        ]
        coverage = len(covered) / total if total else 0.0
        errors = sum(1 for item in covered if not item.correct)
        risk = errors / len(covered) if covered else 0.0
        points.append(
            RiskCoveragePoint(threshold=threshold, coverage=coverage, risk=risk)
        )
    return points


def expected_calibration_error(
    predictions: Sequence[Prediction], *, bins: int = 10
) -> float:
    """Mean gap between stated confidence and observed accuracy.

    Zero means a layer that says 0.8 is right 80% of the time. A layer can have
    excellent accuracy and terrible calibration, and only the latter tells you
    whether its confidence is safe to threshold on -- which is the whole
    premise of an escalation ladder.

    Args:
        predictions: The cases to score. Abstentions are excluded; they carry
            no confidence claim to check.
        bins: Number of equal-width confidence bins.

    Returns:
        The ECE in [0, 1], or 0.0 when there is nothing to score.
    """
    decided = _decided(predictions)
    if not decided or bins < 1:
        return 0.0

    buckets: list[list[Prediction]] = [[] for _ in range(bins)]
    for item in decided:
        confidence = min(max(item.confidence, 0.0), 1.0)
        index = min(int(confidence * bins), bins - 1)
        buckets[index].append(item)

    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        bucket_accuracy = sum(1 for item in bucket if item.correct) / len(bucket)
        bucket_confidence = sum(item.confidence for item in bucket) / len(bucket)
        error += (len(bucket) / len(decided)) * abs(bucket_accuracy - bucket_confidence)
    return error


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the top-k retrieved items that are relevant.

    Args:
        retrieved: Retrieved identifiers, best first.
        relevant: The gold relevant identifiers.
        k: Cut-off rank.

    Returns:
        Precision@k in [0, 1], or 0.0 when ``k`` is not positive.
    """
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    top = list(retrieved)[:k]
    if not top:
        return 0.0
    return sum(1 for item in top if item in relevant_set) / len(top)


def recall_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of gold relevant items present in the top-k retrieved.

    Args:
        retrieved: Retrieved identifiers, best first.
        relevant: The gold relevant identifiers.
        k: Cut-off rank.

    Returns:
        Recall@k in [0, 1], or 0.0 when there are no relevant items.
    """
    relevant_set = set(relevant)
    if not relevant_set or k <= 0:
        return 0.0
    top = set(list(retrieved)[:k])
    return len(top & relevant_set) / len(relevant_set)


def mean_reciprocal_rank(rankings: Sequence[tuple[Sequence[str], Iterable[str]]]) -> float:
    """Mean of 1/rank of the first relevant item, across a batch of queries.

    Unlike precision/recall@k, MRR is not cut off at a fixed k -- it rewards
    a relevant item appearing anywhere in the ranking, weighted by how close
    to the top it is. That makes it the right complement to precision@k
    here: precision@k tells you whether the writer's fixed budget (k source
    chunks) would have included a relevant one, MRR tells you how far a
    chunking configuration pushed the first relevant hit down the ranking
    even when it stayed inside that budget.

    Args:
        rankings: One ``(retrieved, relevant)`` pair per query -- retrieved
            identifiers best-first, and the gold relevant identifiers for
            that query.

    Returns:
        The mean reciprocal rank in [0, 1], or 0.0 for an empty input. A
        query with no relevant item found anywhere in ``retrieved``
        contributes 0.0, not an excluded term.
    """
    if not rankings:
        return 0.0

    reciprocal_ranks = []
    for retrieved, relevant in rankings:
        relevant_set = set(relevant)
        rank = next(
            (index for index, item in enumerate(retrieved, start=1) if item in relevant_set),
            None,
        )
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)


def hit_rate_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Whether at least one relevant item lands in the top-k, as 1.0 or 0.0.

    The coarsest of the ranking metrics here on purpose: it answers "would
    the writer have seen anything relevant at all", collapsing rank position
    and count into a single pass/fail per query. Aggregate hit_rate_at_k
    across a gold set for the share of queries a configuration failed
    outright, independent of how well it did on the ones it got right.

    Args:
        retrieved: Retrieved identifiers, best first.
        relevant: The gold relevant identifiers.
        k: Cut-off rank.

    Returns:
        1.0 if any of the top-k retrieved items is relevant, else 0.0. 0.0
        when ``k`` is not positive or there are no relevant items.
    """
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    top = set(list(retrieved)[:k])
    return 1.0 if top & relevant_set else 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Normalised discounted cumulative gain at k, for binary relevance.

    Unlike precision/recall@k, this is rank-sensitive within the cut-off: a
    relevant chunk at position 1 counts more than the same chunk at position
    k, which is what actually matters here -- the writer's prompt lists
    source chunks in retrieval order, and a model is more likely to draw on
    the passages nearer the top.

    Args:
        retrieved: Retrieved identifiers, best first.
        relevant: The gold relevant identifiers.
        k: Cut-off rank.

    Returns:
        nDCG@k in [0, 1]. 0.0 when ``k`` is not positive or there are no
        relevant items (an ideal ranking would be undefined); 1.0 for a
        ranking that places every relevant item as high as it can go.
    """
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0

    top = list(retrieved)[:k]
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(top, start=1)
        if item in relevant_set
    )

    ideal_hits = min(len(relevant_set), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))

    return dcg / idcg if idcg else 0.0


def binary_rates(pairs: Sequence[tuple[bool, bool]]) -> BinaryRates:
    """Tally a sequence of (expected, predicted) booleans.

    Used for the draft gate, where the question is not "which label" but "does
    this draft need a human?". The false-positive rate is the headline number
    there: every false positive is a HITL interruption a correct draft did not
    need.

    Args:
        pairs: ``(expected, predicted)`` tuples.

    Returns:
        The tallied rates.
    """
    return BinaryRates(
        true_positive=sum(
            1 for expected, predicted in pairs if expected and predicted
        ),
        false_positive=sum(
            1 for expected, predicted in pairs if not expected and predicted
        ),
        true_negative=sum(
            1 for expected, predicted in pairs if not expected and not predicted
        ),
        false_negative=sum(
            1 for expected, predicted in pairs if expected and not predicted
        ),
    )
