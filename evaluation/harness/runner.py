"""Runs a decision function over a gold set and records what it did.

Deliberately knows nothing about *which* decision is being measured. A suite
supplies a JSONL gold set and a callable; the runner loads, times, and collects.
That split is what lets the intent gate and the draft gate share one report
format, and what will let a future layer be measured without touching this file.

The runner never catches a case's exception into a "wrong answer" -- a decision
function that raises is a defect, not a misclassification, and folding the two
together would let a crash quietly read as a plausible accuracy drop.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

#: Repository root, resolved from this file rather than the working directory so
#: `make eval` and a bare `python -m` invocation find the same gold sets.
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "evaluation" / "datasets"


@dataclass(frozen=True)
class EvalCase:
    """One gold-set row.

    Attributes:
        id: Stable identifier, used to name the case in reports and diffs.
        category: The failure class this case probes (``inversion``,
            ``paraphrase``, ...). Reports break results down by it, because an
            overall average hides exactly the narrow-scope failures the gold set
            was written to expose.
        payload: The inputs handed to the decision function.
        expected: The gold answer.
    """

    id: str
    category: str
    payload: dict[str, Any]
    expected: dict[str, Any]


@dataclass(frozen=True)
class CaseResult:
    """What the decision function produced for one case.

    Attributes:
        case: The case that was run.
        observed: The decision function's output, as a plain dict so the report
            layer can serialise it without knowing the suite.
        duration_ms: Wall-clock time for this single call.
    """

    case: EvalCase
    observed: dict[str, Any]
    duration_ms: float


@dataclass
class EvalRun:
    """A complete pass of one suite over one gold set."""

    suite: str
    dataset: str
    results: list[CaseResult] = field(default_factory=list)
    started_at: str = ""

    @property
    def total_ms(self) -> float:
        """Summed wall-clock time across every case."""
        return sum(result.duration_ms for result in self.results)

    def by_category(self) -> dict[str, list[CaseResult]]:
        """Group results by the case category, preserving gold-set order."""
        grouped: dict[str, list[CaseResult]] = {}
        for result in self.results:
            grouped.setdefault(result.case.category, []).append(result)
        return grouped


def load_cases(
    dataset: str, *, dataset_dir: Optional[Path] = None
) -> list[EvalCase]:
    """Read a JSONL gold set into cases.

    Every row must carry ``id`` and ``category``; everything under ``expected``
    is the gold answer and every other key is an input. Keeping the split
    implicit like this means adding an input to a suite does not require a
    schema change here.

    Args:
        dataset: File name under ``evaluation/datasets`` (with or without the
            ``.jsonl`` suffix).
        dataset_dir: Override for the dataset directory, for tests.

    Returns:
        The cases, in file order.

    Raises:
        FileNotFoundError: When the gold set does not exist.
        ValueError: When a row is missing ``id`` or ``expected``.
    """
    directory = dataset_dir or DATASET_DIR
    name = dataset if dataset.endswith(".jsonl") else f"{dataset}.jsonl"
    path = directory / name

    if not path.exists():
        raise FileNotFoundError(f"Gold set not found: {path}")

    cases: list[EvalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            row = json.loads(stripped)

            if "id" not in row:
                raise ValueError(f"{path}:{line_number} is missing 'id'")
            if "expected" not in row:
                raise ValueError(f"{path}:{line_number} is missing 'expected'")

            payload = {
                key: value
                for key, value in row.items()
                if key not in {"id", "category", "expected", "note"}
            }
            cases.append(
                EvalCase(
                    id=str(row["id"]),
                    category=str(row.get("category", "uncategorised")),
                    payload=payload,
                    expected=row["expected"],
                )
            )
    return cases


def run_cases(
    suite: str,
    dataset: str,
    cases: Iterable[EvalCase],
    decide: Callable[[EvalCase], dict[str, Any]],
) -> EvalRun:
    """Run every case through ``decide`` and record the outcome.

    Args:
        suite: Suite name, used in the report header.
        dataset: Gold-set name, recorded so a report states what it measured.
        cases: The cases to run.
        decide: Called once per case; returns the suite's observation dict.

    Returns:
        The completed run.
    """
    run = EvalRun(
        suite=suite,
        dataset=dataset,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    for case in cases:
        start = time.perf_counter()
        observed = decide(case)
        duration_ms = (time.perf_counter() - start) * 1000.0
        run.results.append(
            CaseResult(case=case, observed=observed, duration_ms=duration_ms)
        )

    return run
