"""Guards the evaluation metrics against silently changing what they measure.

Every threshold in the deterministic decision layer is going to be calibrated
against numbers these functions produce, so a metric that quietly changes
meaning would move every calibrated constant with it and there would be nothing
to catch it. The cases below are small enough to verify by hand.

The abstention-aware behaviour is the part most worth pinning: ``accuracy``
defaults to scoring only the decided subset, and ``per_label_scores`` charges an
abstention against recall but not against another label's precision. Both are
deliberate, and both are easy to "simplify" into the wrong thing.
"""

import pytest

from evaluation.metrics import (
    Prediction,
    abstention_rate,
    accuracy,
    binary_rates,
    confusion_matrix,
    expected_calibration_error,
    macro_f1,
    per_label_scores,
    precision_at_k,
    recall_at_k,
    risk_coverage_curve,
)


def test_accuracy_over_decided_ignores_abstentions():
    """Two right, one wrong, one abstained -> 2/3 decided, 2/4 overall."""
    predictions = [
        Prediction(expected="draft", predicted="draft", confidence=1.0),
        Prediction(expected="chat", predicted="chat", confidence=1.0),
        Prediction(expected="analyze", predicted="chat", confidence=1.0),
        Prediction(expected="draft", abstained=True),
    ]

    assert accuracy(predictions) == pytest.approx(2 / 3)
    assert accuracy(predictions, over_decided=False) == pytest.approx(0.5)


def test_abstention_rate_counts_only_abstentions():
    predictions = [
        Prediction(expected="chat", predicted="chat", confidence=1.0),
        Prediction(expected="chat", abstained=True),
        Prediction(expected="draft", abstained=True),
    ]

    assert abstention_rate(predictions) == pytest.approx(2 / 3)


def test_empty_input_never_raises():
    """The harness runs on filtered subsets; an empty category must not blow up."""
    assert accuracy([]) == 0.0
    assert abstention_rate([]) == 0.0
    assert macro_f1([]) == 0.0
    assert expected_calibration_error([]) == 0.0
    assert confusion_matrix([]) == {}
    assert per_label_scores([]) == []


def test_confusion_matrix_records_abstentions_as_their_own_column():
    """An abstention must stay visible, not vanish from the gold row."""
    predictions = [
        Prediction(expected="draft", predicted="draft", confidence=1.0),
        Prediction(expected="draft", predicted="analyze", confidence=1.0),
        Prediction(expected="draft", abstained=True),
    ]

    matrix = confusion_matrix(predictions)

    assert matrix == {"draft": {"draft": 1, "analyze": 1, "<abstain>": 1}}
    assert sum(matrix["draft"].values()) == 3


def test_per_label_scores_charge_abstention_to_recall_only():
    """`draft` loses recall for abstaining; `chat` keeps perfect precision."""
    predictions = [
        Prediction(expected="draft", predicted="draft", confidence=1.0),
        Prediction(expected="draft", abstained=True),
        Prediction(expected="chat", predicted="chat", confidence=1.0),
    ]

    scores = {score.label: score for score in per_label_scores(predictions)}

    assert scores["draft"].support == 2
    assert scores["draft"].recall == pytest.approx(0.5)
    assert scores["draft"].precision == pytest.approx(1.0)
    assert scores["chat"].precision == pytest.approx(1.0)
    assert scores["chat"].recall == pytest.approx(1.0)


def test_macro_f1_weights_rare_labels_equally():
    """Nine right majority cases must not paper over one wholly failed label."""
    predictions = [
        Prediction(expected="chat", predicted="chat", confidence=1.0) for _ in range(9)
    ]
    predictions.append(
        Prediction(expected="document_qa", predicted="chat", confidence=1.0)
    )

    # Micro accuracy would read 0.9 here; macro F1 must not.
    assert accuracy(predictions) == pytest.approx(0.9)
    assert macro_f1(predictions) < 0.6


def test_risk_coverage_curve_trades_coverage_for_risk():
    """Raising the cut-off must drop coverage and drop risk with it."""
    predictions = [
        Prediction(expected="draft", predicted="draft", confidence=0.9),
        Prediction(expected="chat", predicted="chat", confidence=0.9),
        Prediction(expected="analyze", predicted="chat", confidence=0.2),
    ]

    points = {point.threshold: point for point in risk_coverage_curve(predictions)}

    assert points[0.0].coverage == pytest.approx(1.0)
    assert points[0.0].risk == pytest.approx(1 / 3)
    assert points[0.5].coverage == pytest.approx(2 / 3)
    assert points[0.5].risk == pytest.approx(0.0)


def test_risk_coverage_curve_reports_zero_risk_at_empty_coverage():
    """Above every confidence there is nothing covered; risk must not divide by zero."""
    predictions = [Prediction(expected="chat", predicted="draft", confidence=0.1)]

    top = risk_coverage_curve(predictions)[-1]

    assert top.threshold == pytest.approx(1.0)
    assert top.coverage == pytest.approx(0.0)
    assert top.risk == pytest.approx(0.0)


def test_expected_calibration_error_is_zero_for_a_calibrated_layer():
    """Confidence 1.0 and always right -> nothing to correct."""
    predictions = [
        Prediction(expected="chat", predicted="chat", confidence=1.0) for _ in range(4)
    ]

    assert expected_calibration_error(predictions) == pytest.approx(0.0)


def test_expected_calibration_error_catches_overconfidence():
    """Claiming 1.0 while being right half the time is a 0.5 gap."""
    predictions = [
        Prediction(expected="chat", predicted="chat", confidence=1.0),
        Prediction(expected="chat", predicted="draft", confidence=1.0),
    ]

    assert expected_calibration_error(predictions) == pytest.approx(0.5)


def test_precision_and_recall_at_k():
    retrieved = ["a", "b", "c", "d"]
    relevant = ["a", "c", "e"]

    assert precision_at_k(retrieved, relevant, 2) == pytest.approx(0.5)
    assert recall_at_k(retrieved, relevant, 2) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, relevant, 4) == pytest.approx(2 / 3)
    assert precision_at_k(retrieved, relevant, 0) == 0.0
    assert recall_at_k(retrieved, [], 4) == 0.0


def test_binary_rates_headline_is_the_false_positive_rate():
    """One clean draft wrongly sent to a human out of two clean drafts."""
    pairs = [
        (True, True),  # needed a human, got one
        (False, True),  # clean draft, interrupted anyway
        (False, False),  # clean draft, passed
        (True, False),  # needed a human, slipped through
    ]

    rates = binary_rates(pairs)

    assert rates.true_positive == 1
    assert rates.false_positive == 1
    assert rates.true_negative == 1
    assert rates.false_negative == 1
    assert rates.false_positive_rate == pytest.approx(0.5)
    assert rates.false_negative_rate == pytest.approx(0.5)
    assert rates.accuracy == pytest.approx(0.5)
