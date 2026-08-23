"""Reports observed per-node latency against BudgetPolicy.node_seconds.

Usage (inside the backend container, against the running `backend` service):

    docker compose run --rm backend python -m evaluation.latency.budget_report
    docker compose run --rm backend python -m evaluation.latency.budget_report --base-url http://host.docker.internal:8000

Deliberately reads *observed* durations from the running app's own
``/metrics`` (the real ``kachow_node_duration_seconds`` histogram, labelled
``graph="node_budget"``) rather than re-timing anything synthetically --
see this package's own README for why. Production traffic (or a k6 run,
Workstream E2) is what actually produced the numbers; this script's only
job is turning the raw histogram buckets into p50/p95/p99 and comparing
them to the budget.

Quantile estimation is linear interpolation within the bucket the target
quantile falls in -- the same algorithm PromQL's own ``histogram_quantile()``
uses, reimplemented here in pure stdlib since this script talks to
``/metrics`` directly rather than a Prometheus server (this repo has none
running by default -- see ``docs/deployment/observability.md`` for when one
is configured).

"Budget nearly exhausted": p95 > 0.8x the node's ``BudgetPolicy`` budget.
0.8, not 1.0, on purpose -- the same headroom a capacity-planning read of
this report needs *before* a node starts actually timing out and forcing
``NodeBudgetExceeded``'s degrade path, not after.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from prometheus_client.parser import text_string_to_metric_families

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ai.policy import get_policy  # noqa: E402

_METRIC_NAME = "kachow_node_duration_seconds"
_NEAR_EXHAUSTION_RATIO = 0.8


@dataclass(frozen=True)
class NodeHistogram:
    node: str
    buckets: list[tuple[float, float]]  # (le, cumulative_count), ascending le
    count: float
    total_seconds: float


def fetch_metrics_text(base_url: str) -> str:
    response = httpx.get(f"{base_url.rstrip('/')}/metrics", timeout=10.0)
    response.raise_for_status()
    return response.text


def parse_node_histograms(metrics_text: str, *, graph: str = "node_budget") -> dict[str, NodeHistogram]:
    """Extract per-node histograms for ``status="completed"`` samples only.

    A failed/timed-out node's duration is real, but mixing it into the same
    quantiles as successful runs would understate how long a *successful*
    call actually takes -- the number this report exists to compare against
    the budget. Failure counts are surfaced separately by the caller if it
    wants them (not today: see this module's own scope note in the README).
    """
    buckets_by_node: dict[str, list[tuple[float, float]]] = {}
    counts_by_node: dict[str, float] = {}
    sums_by_node: dict[str, float] = {}

    for family in text_string_to_metric_families(metrics_text):
        if family.name != _METRIC_NAME:
            continue
        for sample in family.samples:
            labels = sample.labels
            if labels.get("graph") != graph or labels.get("status") != "completed":
                continue
            node = labels.get("node", "")
            if sample.name.endswith("_bucket"):
                le = float(labels["le"])
                buckets_by_node.setdefault(node, []).append((le, sample.value))
            elif sample.name.endswith("_count"):
                counts_by_node[node] = sample.value
            elif sample.name.endswith("_sum"):
                sums_by_node[node] = sample.value

    result: dict[str, NodeHistogram] = {}
    for node, buckets in buckets_by_node.items():
        buckets.sort(key=lambda pair: pair[0])
        result[node] = NodeHistogram(
            node=node,
            buckets=buckets,
            count=counts_by_node.get(node, 0.0),
            total_seconds=sums_by_node.get(node, 0.0),
        )
    return result


def estimate_quantile(histogram: NodeHistogram, quantile: float) -> Optional[float]:
    """Linear interpolation within the bucket the target quantile falls in.

    Returns ``None`` when there are zero observations -- a node this
    quiet has nothing to report, not a p95 of 0.
    """
    if histogram.count <= 0:
        return None

    target_rank = quantile * histogram.count
    lower_le, lower_count = 0.0, 0.0
    for le, cumulative_count in histogram.buckets:
        if cumulative_count >= target_rank:
            if le == float("inf"):
                # The target falls past the highest finite bucket boundary --
                # cannot interpolate a fractional position within "infinity",
                # so report the last finite boundary as a floor estimate.
                return lower_le
            if cumulative_count == lower_count:
                return le
            fraction = (target_rank - lower_count) / (cumulative_count - lower_count)
            return lower_le + fraction * (le - lower_le)
        lower_le, lower_count = le, cumulative_count
    return lower_le


def build_report(histograms: dict[str, NodeHistogram], node_seconds: dict[str, float]) -> list[dict]:
    rows = []
    for node in sorted(set(node_seconds) | set(histograms)):
        budget = node_seconds.get(node)
        histogram = histograms.get(node)
        p50 = estimate_quantile(histogram, 0.50) if histogram else None
        p95 = estimate_quantile(histogram, 0.95) if histogram else None
        p99 = estimate_quantile(histogram, 0.99) if histogram else None
        near_exhaustion = (
            budget is not None and p95 is not None and p95 > _NEAR_EXHAUSTION_RATIO * budget
        )
        rows.append(
            {
                "node": node,
                "budget_seconds": budget,
                "observations": histogram.count if histogram else 0,
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "near_exhaustion": near_exhaustion,
            }
        )
    return rows


def format_report(rows: list[dict]) -> str:
    lines = [
        f"{'node':<25} {'budget(s)':>10} {'obs':>6} {'p50(s)':>8} {'p95(s)':>8} {'p99(s)':>8}  flag",
        "-" * 80,
    ]
    for row in rows:
        budget_str = f"{row['budget_seconds']:.0f}" if row["budget_seconds"] is not None else "-"
        p50_str = f"{row['p50']:.2f}" if row["p50"] is not None else "no data"
        p95_str = f"{row['p95']:.2f}" if row["p95"] is not None else "no data"
        p99_str = f"{row['p99']:.2f}" if row["p99"] is not None else "no data"
        flag = "BUDGET NEARLY EXHAUSTED" if row["near_exhaustion"] else ""
        lines.append(
            f"{row['node']:<25} {budget_str:>10} {row['observations']:>6.0f} "
            f"{p50_str:>8} {p95_str:>8} {p99_str:>8}  {flag}"
        )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="http://backend:8000",
        help="Base URL of the running backend (default: the compose service DNS name).",
    )
    args = parser.parse_args(argv)

    metrics_text = fetch_metrics_text(args.base_url)
    histograms = parse_node_histograms(metrics_text)
    node_seconds = dict(get_policy().budget.node_seconds)

    rows = build_report(histograms, node_seconds)
    print(format_report(rows))

    unobserved = [row["node"] for row in rows if row["observations"] == 0 and row["budget_seconds"] is not None]
    if unobserved:
        print()
        print(
            f"No observations yet for: {', '.join(unobserved)} -- either no traffic has "
            "exercised them since the last restart, or the node isn't instrumented "
            "yet (writer/assist are a known, disclosed gap; see this package's README)."
        )

    exhausted = [row["node"] for row in rows if row["near_exhaustion"]]
    if exhausted:
        print()
        print(f"BUDGET NEARLY EXHAUSTED for: {', '.join(exhausted)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
