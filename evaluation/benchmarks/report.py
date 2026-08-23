"""Compares a fresh pytest-benchmark run against the committed baseline.

Usage (inside the backend container -- see ``make benchmark``)::

    python evaluation/benchmarks/report.py

Why this exists instead of pytest-benchmark's own ``--benchmark-compare-fail``:
that flag's percentage syntax caps at 99% (``pytest_benchmark.utils.
parse_compare_fail``'s own regex is ``[0-9]?[0-9]%``, i.e. at most two
digits), so the plan's own target -- fail only on a >3x (200%+) regression,
never on ordinary machine noise -- cannot be expressed with it at all. This
script reads the same JSON schema pytest-benchmark's own ``--benchmark-save``
writes and does the ratio check directly, mirroring
``evaluation/generate_report.py``'s own baseline-diffing idiom elsewhere in
this repo (stdlib-only, deterministic, a table plus a hard exit code).

Regression threshold: ``_REGRESSION_RATIO_THRESHOLD`` (3.0, i.e. current
mean > 3x baseline mean fails) -- coarse and deliberately so, matching the
project's `docs/evaluation` philosophy of gating only on gross regressions
where hardware variance (3-5x between a laptop and a CI runner, see this
project's own retrieval/eval docs on why wall-clock numbers aren't trusted
absolutely) cannot be the explanation.
"""

import json
import sys
from pathlib import Path
from typing import Optional

BENCHMARKS_DIR = Path(__file__).resolve().parent

_REGRESSION_RATIO_THRESHOLD = 3.0


def _find_one(pattern: str) -> Optional[Path]:
    matches = sorted(BENCHMARKS_DIR.glob(pattern))
    return matches[-1] if matches else None


def _load_means(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {bench["name"]: bench["stats"]["mean"] for bench in payload["benchmarks"]}


def main() -> int:
    baseline_path = _find_one("*/*_baseline.json")
    latest_path = _find_one("*/*_latest.json")

    if baseline_path is None:
        print(
            "No committed baseline found under evaluation/benchmarks/*/*_baseline.json. "
            "Run `make benchmark-baseline` once and commit the result.",
            file=sys.stderr,
        )
        return 1
    if latest_path is None:
        print(
            "No fresh run found under evaluation/benchmarks/*/*_latest.json. "
            "`make benchmark` should have produced one before calling this script.",
            file=sys.stderr,
        )
        return 1

    baseline_means = _load_means(baseline_path)
    latest_means = _load_means(latest_path)

    print(f"Baseline: {baseline_path.relative_to(BENCHMARKS_DIR.parent.parent)}")
    print(f"Latest:   {latest_path.relative_to(BENCHMARKS_DIR.parent.parent)}")
    print()
    print(f"{'benchmark':<55} {'baseline (us)':>14} {'latest (us)':>14} {'ratio':>8}")
    print("-" * 95)

    regressions: list[str] = []
    missing = sorted(set(latest_means) - set(baseline_means))
    for name in sorted(latest_means):
        if name not in baseline_means:
            continue
        baseline_mean = baseline_means[name]
        latest_mean = latest_means[name]
        ratio = latest_mean / baseline_mean if baseline_mean > 0 else float("inf")
        flag = " <-- REGRESSION" if ratio > _REGRESSION_RATIO_THRESHOLD else ""
        print(
            f"{name:<55} {baseline_mean * 1e6:>14.2f} {latest_mean * 1e6:>14.2f} {ratio:>7.2f}x{flag}"
        )
        if ratio > _REGRESSION_RATIO_THRESHOLD:
            regressions.append(name)

    if missing:
        print()
        print(f"New benchmark(s) with no baseline entry (not gated): {', '.join(missing)}")

    print()
    if regressions:
        print(
            f"FAIL: {len(regressions)} benchmark(s) regressed >{_REGRESSION_RATIO_THRESHOLD:.0f}x "
            f"against the committed baseline: {', '.join(regressions)}"
        )
        return 1

    print("OK: no benchmark regressed beyond the gross-regression threshold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
