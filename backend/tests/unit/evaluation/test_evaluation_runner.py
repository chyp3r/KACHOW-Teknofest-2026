"""Guards the gold-set loader's input/expected split and its failure modes.

The loader treats every key that is not `id`/`category`/`expected`/`note` as an
input, which is what lets a suite gain an input without a schema change here. It
is also what makes a typo in a gold-set key silently become an ignored input
rather than an error, so the two required keys are checked loudly and pinned by
these tests.

The runner deliberately does not catch exceptions from a decision function: a
crash is a defect, not a misclassification, and swallowing it would let a broken
production function read as a plausible accuracy drop.
"""

import json

import pytest

from evaluation.harness.runner import EvalCase, load_cases, run_cases


def _write_dataset(directory, name, rows):
    path = directory / f"{name}.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_load_cases_splits_inputs_from_expected(tmp_path):
    _write_dataset(
        tmp_path,
        "sample",
        [
            {
                "id": "case_01",
                "category": "inversion",
                "note": "human-only annotation",
                "message": "taslağı analiz et",
                "document_attached": True,
                "expected": {"intent": "analyze"},
            }
        ],
    )

    cases = load_cases("sample", dataset_dir=tmp_path)

    assert len(cases) == 1
    assert cases[0].id == "case_01"
    assert cases[0].category == "inversion"
    assert cases[0].payload == {"message": "taslağı analiz et", "document_attached": True}
    assert cases[0].expected == {"intent": "analyze"}


def test_load_cases_accepts_name_with_or_without_suffix(tmp_path):
    _write_dataset(tmp_path, "sample", [{"id": "a", "expected": {}}])

    assert load_cases("sample", dataset_dir=tmp_path)
    assert load_cases("sample.jsonl", dataset_dir=tmp_path)


def test_load_cases_skips_blank_and_comment_lines(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '// leading comment\n'
        '\n'
        '{"id": "a", "expected": {}}\n'
        '   \n'
        '{"id": "b", "expected": {}}\n',
        encoding="utf-8",
    )

    assert [case.id for case in load_cases("sample", dataset_dir=tmp_path)] == ["a", "b"]


def test_load_cases_defaults_missing_category(tmp_path):
    _write_dataset(tmp_path, "sample", [{"id": "a", "expected": {}}])

    assert load_cases("sample", dataset_dir=tmp_path)[0].category == "uncategorised"


@pytest.mark.parametrize(
    "row, missing",
    [
        ({"category": "x", "expected": {}}, "id"),
        ({"id": "a", "category": "x"}, "expected"),
    ],
)
def test_load_cases_rejects_rows_missing_required_keys(tmp_path, row, missing):
    _write_dataset(tmp_path, "sample", [row])

    with pytest.raises(ValueError, match=missing):
        load_cases("sample", dataset_dir=tmp_path)


def test_load_cases_reports_the_missing_file_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.jsonl"):
        load_cases("nope", dataset_dir=tmp_path)


def test_run_cases_records_every_case_in_order():
    cases = [
        EvalCase(id="a", category="x", payload={"n": 1}, expected={}),
        EvalCase(id="b", category="y", payload={"n": 2}, expected={}),
    ]

    run = run_cases("suite", "dataset", cases, lambda case: {"n": case.payload["n"] * 10})

    assert [result.case.id for result in run.results] == ["a", "b"]
    assert [result.observed["n"] for result in run.results] == [10, 20]
    assert run.suite == "suite"
    assert run.dataset == "dataset"
    assert run.started_at
    assert run.total_ms >= 0.0


def test_run_cases_groups_by_category():
    cases = [
        EvalCase(id="a", category="x", payload={}, expected={}),
        EvalCase(id="b", category="y", payload={}, expected={}),
        EvalCase(id="c", category="x", payload={}, expected={}),
    ]

    grouped = run_cases("s", "d", cases, lambda case: {}).by_category()

    assert sorted(grouped) == ["x", "y"]
    assert [result.case.id for result in grouped["x"]] == ["a", "c"]


def test_run_cases_lets_a_decision_function_crash_propagate():
    """A raising decision function is a defect, not a wrong answer."""

    def boom(case):
        raise RuntimeError("decision function is broken")

    cases = [EvalCase(id="a", category="x", payload={}, expected={})]

    with pytest.raises(RuntimeError, match="broken"):
        run_cases("s", "d", cases, boom)
