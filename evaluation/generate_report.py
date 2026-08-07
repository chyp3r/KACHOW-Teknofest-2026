"""Runs the evaluation suites and writes a Markdown + JSON report.

Usage (inside the backend container -- see ``make eval``)::

    python -m evaluation.generate_report --suite all
    python -m evaluation.generate_report --suite intents --label after-scoring
    python -m evaluation.generate_report --suite all --baseline evaluation/reports/intents-baseline.json

The JSON file is the machine-readable artefact a later run diffs against; the
Markdown is what gets read in a pull request. Both are written, always, because
a report that only exists in a terminal cannot be a review artefact.

The per-category breakdown is the point of the whole thing. An overall accuracy
figure averages away exactly the narrow-scope failures the gold sets were
written to expose -- a decision layer can score well overall while getting every
single paraphrased case wrong, and only the breakdown shows it.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from app.ai.policy import POLICY_VERSION
from evaluation.harness import draft_suite, intent_suite
from evaluation.harness.runner import REPO_ROOT, EvalRun
from evaluation.metrics import (
    Prediction,
    abstention_rate,
    accuracy,
    confusion_matrix,
    expected_calibration_error,
    macro_f1,
    per_label_scores,
    risk_coverage_curve,
)

REPORT_DIR = REPO_ROOT / "evaluation" / "reports"

SUITES = ("intents", "drafts")


def _intent_summary(run: EvalRun) -> dict[str, Any]:
    """Score an intent run into a serialisable summary."""
    predictions = intent_suite.to_predictions(run)

    categories: dict[str, dict[str, Any]] = {}
    for category, results in run.by_category().items():
        subset = intent_suite.to_predictions(
            EvalRun(suite=run.suite, dataset=run.dataset, results=results)
        )
        categories[category] = {
            "cases": len(subset),
            "accuracy_over_all": round(accuracy(subset, over_decided=False), 4),
            "accuracy_over_decided": round(accuracy(subset), 4),
            "abstention_rate": round(abstention_rate(subset), 4),
        }

    return {
        "cases": len(predictions),
        "macro_f1": round(macro_f1(predictions), 4),
        "accuracy_over_all": round(accuracy(predictions, over_decided=False), 4),
        "accuracy_over_decided": round(accuracy(predictions), 4),
        "abstention_rate": round(abstention_rate(predictions), 4),
        "expected_calibration_error": round(
            expected_calibration_error(predictions), 4
        ),
        # Only meaningful for the intent suite: how much of the ladder's
        # decided traffic each rung actually produced, and how often it
        # asked the user instead of committing. Neither is derivable from
        # the accuracy/F1 numbers above -- a ladder can hold accuracy steady
        # while quietly shifting its cost profile toward asking more
        # questions, and this is what would show it.
        "source_distribution": intent_suite.source_distribution(run),
        "clarify_rate": round(intent_suite.clarify_rate(run), 4),
        "per_label": [asdict(score) for score in per_label_scores(predictions)],
        "confusion_matrix": confusion_matrix(predictions),
        "risk_coverage": [
            asdict(point) for point in risk_coverage_curve(predictions)
        ],
        "by_category": categories,
        "failures": intent_suite.failures(run),
    }


def _draft_summary(run: EvalRun) -> dict[str, Any]:
    """Score a draft run into a serialisable summary."""
    rates = draft_suite.to_rates(run)

    categories: dict[str, dict[str, Any]] = {}
    for category, results in run.by_category().items():
        subset = draft_suite.to_rates(
            EvalRun(suite=run.suite, dataset=run.dataset, results=results)
        )
        categories[category] = {
            "cases": len(results),
            "accuracy": round(subset.accuracy, 4),
            "false_positive": subset.false_positive,
            "false_negative": subset.false_negative,
        }

    return {
        "cases": len(run.results),
        "accuracy": round(rates.accuracy, 4),
        "false_positive_rate": round(rates.false_positive_rate, 4),
        "false_negative_rate": round(rates.false_negative_rate, 4),
        "counts": asdict(rates),
        "by_category": categories,
        "failures": draft_suite.failures(run),
        "claim_detection_gaps": draft_suite.claim_detection_gaps(run),
    }


def _run_suite(name: str, *, with_model: bool = False) -> tuple[EvalRun, dict[str, Any]]:
    """Run one suite and score it.

    Args:
        name: ``"intents"`` or ``"drafts"``.
        with_model: Only meaningful for ``"intents"`` -- wires a real
            fast-tier model into the model band instead of the default fully
            offline run (see ``intent_suite.run_with_model``). Ignored for
            ``"drafts"``, which has no model band to begin with.

    Returns:
        The run and its summary.

    Raises:
        ValueError: For an unknown suite name.
    """
    if name == "intents":
        run = intent_suite.run_with_model() if with_model else intent_suite.run()
        return run, _intent_summary(run)
    if name == "drafts":
        run = draft_suite.run()
        return run, _draft_summary(run)
    raise ValueError(f"Unknown suite: {name}")


def _format_intent_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the intent summary as Markdown lines."""
    lines = [
        "### Genel",
        "",
        "| Metrik | Değer |",
        "|---|---|",
        f"| Vaka sayısı | {summary['cases']} |",
        f"| Macro F1 | {summary['macro_f1']:.4f} |",
        f"| Doğruluk (tüm vakalar) | {summary['accuracy_over_all']:.4f} |",
        f"| Doğruluk (karar verilenler) | {summary['accuracy_over_decided']:.4f} |",
        f"| Eskalasyon (abstention) oranı | {summary['abstention_rate']:.4f} |",
        f"| **Clarify oranı** (kullanıcıya soru) | **{summary['clarify_rate']:.4f}** |",
        f"| Kalibrasyon hatası (ECE) | {summary['expected_calibration_error']:.4f} |",
        "",
        "### Kaynak dağılımı",
        "",
        "| Kaynak | Vaka |",
        "|---|---|",
    ]
    for source, count in summary["source_distribution"].items():
        lines.append(f"| `{source}` | {count} |")

    lines += [
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | Doğruluk | Eskalasyon |",
        "|---|---|---|---|",
    ]

    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | "
            f"{stats['accuracy_over_all']:.2f} | {stats['abstention_rate']:.2f} |"
        )

    lines += ["", "### Etiket bazında", "", "| Etiket | P | R | F1 | Destek |", "|---|---|---|---|---|"]
    for score in summary["per_label"]:
        lines.append(
            f"| `{score['label']}` | {score['precision']:.2f} | "
            f"{score['recall']:.2f} | {score['f1']:.2f} | {score['support']} |"
        )

    failures = summary["failures"]
    lines += ["", f"### Başarısız vakalar ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += [
            "| ID | Kategori | Mesaj | Beklenen | Gözlenen | Kaynak |",
            "|---|---|---|---|---|---|",
        ]
        for row in failures:
            message = row["message"].replace("|", "\\|")
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | {message} | "
                f"`{row['expected']}` | `{row['observed']}` | `{row['source']}` |"
            )
    return lines


def _format_draft_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the draft summary as Markdown lines."""
    counts = summary["counts"]
    lines = [
        "### Genel",
        "",
        "| Metrik | Değer |",
        "|---|---|",
        f"| Vaka sayısı | {summary['cases']} |",
        f"| Doğruluk | {summary['accuracy']:.4f} |",
        f"| **Yanlış pozitif oranı** (gereksiz HITL) | **{summary['false_positive_rate']:.4f}** |",
        f"| Yanlış negatif oranı (kaçan hata) | {summary['false_negative_rate']:.4f} |",
        f"| TP / FP / TN / FN | {counts['true_positive']} / {counts['false_positive']} "
        f"/ {counts['true_negative']} / {counts['false_negative']} |",
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | Doğruluk | YP | YN |",
        "|---|---|---|---|---|",
    ]

    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | {stats['accuracy']:.2f} | "
            f"{stats['false_positive']} | {stats['false_negative']} |"
        )

    failures = summary["failures"]
    lines += ["", f"### Başarısız vakalar ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += ["| ID | Kategori | Tür | Skor | Bulunan dayanaksız ifadeler |", "|---|---|---|---|---|"]
        for row in failures:
            claims = ", ".join(
                f"{claim['kind']}: {claim['value']}"
                for claim in row["unsupported_claims"]
            )
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | `{row['kind']}` | "
                f"{row['confidence_score']} | {claims or '-'} |"
            )

    gaps = summary["claim_detection_gaps"]
    lines += ["", f"### Dayanaksız ifade sayımı sapmaları ({len(gaps)})", ""]
    if not gaps:
        lines.append("Yok.")
    else:
        lines += ["| ID | Kategori | Beklenen | Gözlenen |", "|---|---|---|---|"]
        for row in gaps:
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | "
                f"{row['expected_claim_count']} | {row['observed_claim_count']} |"
            )
    return lines


def _diff_lines(suite: str, current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Render the headline deltas against a baseline report."""
    keys = (
        ("macro_f1", "Macro F1", True)
        if suite == "intents"
        else ("accuracy", "Doğruluk", True)
    )
    tracked = [keys]
    if suite == "intents":
        tracked += [
            ("accuracy_over_all", "Doğruluk (tüm vakalar)", True),
            ("abstention_rate", "Eskalasyon oranı", False),
            ("clarify_rate", "Clarify oranı", False),
            ("expected_calibration_error", "Kalibrasyon hatası", False),
        ]
    else:
        tracked += [
            ("false_positive_rate", "Yanlış pozitif oranı", False),
            ("false_negative_rate", "Yanlış negatif oranı", False),
        ]

    lines = ["### Baseline karşılaştırması", "", "| Metrik | Baseline | Şimdi | Δ |", "|---|---|---|---|"]
    for key, label, higher_is_better in tracked:
        before = baseline.get(key)
        after = current.get(key)
        if before is None or after is None:
            continue
        delta = after - before
        arrow = "→"
        if delta > 1e-9:
            arrow = "↑" if higher_is_better else "↑ (kötü)"
        elif delta < -1e-9:
            arrow = "↓ (kötü)" if higher_is_better else "↓"
        lines.append(f"| {label} | {before:.4f} | {after:.4f} | {delta:+.4f} {arrow} |")
    return lines


def build_report(
    summaries: dict[str, dict[str, Any]],
    runs: dict[str, EvalRun],
    baseline: Optional[dict[str, Any]] = None,
) -> str:
    """Compose the Markdown report.

    Args:
        summaries: Suite name -> scored summary.
        runs: Suite name -> the run it came from.
        baseline: A previously written report's JSON payload, when comparing.

    Returns:
        The Markdown document.
    """
    lines = [
        "# Deterministik Karar Katmanı Değerlendirme Raporu",
        "",
        "> Bu rapor `make eval` ile üretilir ve **hiç LLM çağrısı içermez**.",
        "> Ölçülen, üretim kodundaki deterministik karar fonksiyonlarının kendisidir.",
        "",
        f"Policy sürümü: `{POLICY_VERSION}`",
        "",
    ]

    for suite in SUITES:
        if suite not in summaries:
            continue
        run = runs[suite]
        lines += [
            f"## Suite: `{suite}`",
            "",
            f"Altın küme: `evaluation/datasets/{run.dataset}.jsonl` · "
            f"Koşu: {run.started_at} · Süre: {run.total_ms:.1f} ms",
            "",
        ]
        if suite == "intents":
            lines += _format_intent_markdown(summaries[suite])
        else:
            lines += _format_draft_markdown(summaries[suite])

        if baseline and suite in baseline.get("suites", {}):
            lines += [""] + _diff_lines(
                suite, summaries[suite], baseline["suites"][suite]
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector, for tests. Defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code. Always 0 on a completed run -- a failing gold-set
        case is a measurement, not a build failure. Regressions are gated by
        `tests/unit/ai/`, not by this report.
    """
    parser = argparse.ArgumentParser(description="Run the deterministic evaluation suites.")
    parser.add_argument("--suite", choices=(*SUITES, "all"), default="all")
    parser.add_argument(
        "--label",
        default="latest",
        help="Report file name suffix, e.g. 'baseline' or 'after-scoring'.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="A previous report's .json to compare the headline metrics against.",
    )
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    parser.add_argument(
        "--with-model",
        action="store_true",
        help=(
            "Intents suite only: wire a real fast-tier model into the "
            "contested band instead of running fully offline. Makes live "
            "Ollama calls -- see `make eval-llm`."
        ),
    )
    args = parser.parse_args(argv)

    selected = SUITES if args.suite == "all" else (args.suite,)

    runs: dict[str, EvalRun] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for suite in selected:
        run, summary = _run_suite(suite, with_model=args.with_model)
        runs[suite] = run
        summaries[suite] = summary

    baseline: Optional[dict[str, Any]] = None
    if args.baseline:
        if not args.baseline.exists():
            print(f"Baseline not found: {args.baseline}", file=sys.stderr)
            return 2
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))

    payload = {
        # Stamped so a report can be attributed to the parameter set that
        # produced it; comparing two runs across a policy bump is comparing
        # two different systems.
        "policy_version": POLICY_VERSION,
        "suites": summaries,
        "meta": {
            suite: {
                "dataset": runs[suite].dataset,
                "started_at": runs[suite].started_at,
                "total_ms": round(runs[suite].total_ms, 3),
            }
            for suite in selected
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.suite}-{args.label}"
    json_path = args.out / f"{stem}.json"
    markdown_path = args.out / f"{stem}.md"

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        build_report(summaries, runs, baseline), encoding="utf-8"
    )

    for suite in selected:
        summary = summaries[suite]
        headline = (
            f"macro_f1={summary['macro_f1']:.4f} "
            f"abstention={summary['abstention_rate']:.4f}"
            if suite == "intents"
            else (
                f"accuracy={summary['accuracy']:.4f} "
                f"false_positive_rate={summary['false_positive_rate']:.4f}"
            )
        )
        print(f"[{suite}] {summary['cases']} vaka · {headline}")

    print(f"\nRapor yazıldı:\n  {json_path}\n  {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
