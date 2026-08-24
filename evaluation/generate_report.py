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
from evaluation.harness import (
    draft_suite,
    evrak_suite,
    intent_suite,
    retrieval_suite,
    trajectory_suite,
)
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

SUITES = ("intents", "drafts", "retrieval", "trajectories", "evrak")


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


def _evrak_summary(run: EvalRun) -> dict[str, Any]:
    """Score an evrak run into a serialisable summary.

    Şartname requirement 5 (mevzuat citation grounding) is scored here too,
    from `evrak_suite.citation_fixture_rates()` -- a fixed fixture, not a
    per-case observation, since a citation's groundedness is a pure function
    of (citation, excerpts), not of a document's text.
    """
    ocr_rates = evrak_suite.ocr_routing_rates(run)
    missing_rates = evrak_suite.missing_field_rates(run)
    extraction = evrak_suite.extraction_totals(run)
    extraction_total = sum(extraction.values())
    citation_rates = evrak_suite.citation_fixture_rates()

    categories: dict[str, dict[str, Any]] = {}
    for category, results in run.by_category().items():
        subset = EvalRun(suite=run.suite, dataset=run.dataset, results=results)
        categories[category] = {
            "cases": len(results),
            "ocr_routing_accuracy": round(evrak_suite.ocr_routing_rates(subset).accuracy, 4),
            "missing_field_false_positive_rate": round(
                evrak_suite.missing_field_rates(subset).false_positive_rate, 4
            ),
        }

    return {
        "cases": len(run.results),
        "ocr_routing_accuracy": round(ocr_rates.accuracy, 4),
        "missing_field_false_positive_rate": round(missing_rates.false_positive_rate, 4),
        "missing_field_false_negative_rate": round(missing_rates.false_negative_rate, 4),
        "missing_field_counts": asdict(missing_rates),
        "extraction_counts": extraction,
        "extraction_correct_rate": round(
            extraction["correct"] / extraction_total, 4
        ) if extraction_total else 0.0,
        "citation_grounding_accuracy": round(citation_rates.accuracy, 4),
        "citation_grounding_counts": asdict(citation_rates),
        "by_category": categories,
        "failures": evrak_suite.failures(run),
    }


def _trajectory_summary(run: EvalRun) -> dict[str, Any]:
    """Score a trajectory run into a serialisable summary."""
    summary = trajectory_suite.sequence_summary(run)

    categories: dict[str, dict[str, Any]] = {}
    for category, results in run.by_category().items():
        subset = trajectory_suite.sequence_summary(
            EvalRun(suite=run.suite, dataset=run.dataset, results=results)
        )
        categories[category] = {
            "cases": subset["cases"],
            "exact_match_rate": round(subset["exact_match_rate"], 4),
            "mean_edit_distance": round(subset["mean_edit_distance"], 4),
        }

    return {
        "cases": summary["cases"],
        "exact_match_rate": round(summary["exact_match_rate"], 4),
        "mean_edit_distance": round(summary["mean_edit_distance"], 4),
        "unexpected_node_rate": round(summary["unexpected_node_rate"], 4),
        "paused_at_mismatches": summary["paused_at_mismatches"],
        "by_category": categories,
        "failures": trajectory_suite.failures(run),
    }


def _retrieval_summary(*, k: int = retrieval_suite.DEFAULT_K) -> tuple[EvalRun, dict[str, Any]]:
    """Run every chunking arm and score them into one comparison summary.

    Unlike the intent/draft suites, "the suite" here is inherently a
    comparison across configurations -- ``--suite retrieval`` means "run
    the A/B", not "run one thing". All arms run in one call so that stays
    true; ``evaluation.harness.retrieval_suite.ARMS`` is the source of
    truth for which configurations exist.

    Returns:
        The baseline arm's ``EvalRun`` (for the report header's
        dataset/timing line -- every arm shares the same gold set and ran
        in the same invocation, so any one of them is representative) and
        the combined summary dict.
    """
    arms: dict[str, dict[str, Any]] = {}
    runs: dict[str, EvalRun] = {}

    for arm_name in retrieval_suite.ARMS:
        run, stats = retrieval_suite.run(arm_name, k=k)
        runs[arm_name] = run
        arms[arm_name] = {
            **retrieval_suite.to_metrics(run, k=k),
            "chunk_count": stats.chunk_count,
            "mean_chunk_length": round(stats.mean_chunk_length, 1),
            "p50_chunk_length": stats.p50_chunk_length,
            "p95_chunk_length": stats.p95_chunk_length,
            "page_attribution_rate": round(stats.page_attribution_rate, 4),
            "answer_span_intactness": round(stats.answer_span_intactness, 4),
            "by_category": {
                category: metrics
                for category, metrics in retrieval_suite.by_category_metrics(run, k=k).items()
            },
        }
        for metric_key in (
            "precision_at_k", "recall_at_k", "hit_rate_at_k",
            "mean_reciprocal_rank", "ndcg_at_k", "mean_yok_top1_score",
        ):
            arms[arm_name][metric_key] = round(arms[arm_name][metric_key], 4)

    baseline = retrieval_suite.BASELINE_ARM
    summary = {
        "k": k,
        "baseline": baseline,
        "arms": arms,
        "delta_vs_baseline": {
            arm_name: {
                metric_key: round(arms[arm_name][metric_key] - arms[baseline][metric_key], 4)
                for metric_key in ("precision_at_k", "ndcg_at_k", "mean_reciprocal_rank")
            }
            for arm_name in arms
            if arm_name != baseline
        },
    }
    return runs[baseline], summary


def _run_suite(
    name: str, *, with_model: bool = False, retrieval_k: int = retrieval_suite.DEFAULT_K
) -> tuple[EvalRun, dict[str, Any]]:
    """Run one suite and score it.

    Args:
        name: ``"intents"``, ``"drafts"``, ``"retrieval"``, ``"trajectories"``
            or ``"evrak"``.
        with_model: Only meaningful for ``"intents"`` -- wires a real
            fast-tier model into the model band instead of the default fully
            offline run (see ``intent_suite.run_with_model``). Ignored for
            every other suite, which has no model band to begin with.
        retrieval_k: Only meaningful for ``"retrieval"`` -- the cut-off
            rank every arm and every rank-sensitive metric uses.

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
    if name == "retrieval":
        return _retrieval_summary(k=retrieval_k)
    if name == "trajectories":
        run = trajectory_suite.run()
        return run, _trajectory_summary(run)
    if name == "evrak":
        run = evrak_suite.run()
        return run, _evrak_summary(run)
    raise ValueError(f"Unknown suite: {name}")


def _format_intent_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the intent summary as Markdown lines."""
    lines = [
        "### Genel",
        "",
        "| Metrik | Değer |",
        "|---|---|",
        f"| Vaka sayısı | {summary['cases']} |",
        f"| **Macro F1** | **{summary['macro_f1']:.4f}** |",
        f"| Doğruluk (tüm vakalar) | {summary['accuracy_over_all']:.4f} |",
        f"| Doğruluk (karar verilenler) | {summary['accuracy_over_decided']:.4f} |",
        f"| Eskalasyon oranı | {summary['abstention_rate']:.4f} |",
        f"| Clarify oranı | {summary['clarify_rate']:.4f} |",
        f"| Kalibrasyon hatası | {summary['expected_calibration_error']:.4f} |",
        "",
        "### Kaynak dağılımı",
        "",
        "| Kaynak | Sayı |",
        "|---|---|",
    ]
    for source, count in sorted(summary["source_distribution"].items()):
        lines.append(f"| `{source}` | {count} |")

    lines += [
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | Doğruluk (tüm) | Doğruluk (kararlı) | Eskalasyon |",
        "|---|---|---|---|---|",
    ]
    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | {stats['accuracy_over_all']:.2f} | "
            f"{stats['accuracy_over_decided']:.2f} | {stats['abstention_rate']:.2f} |"
        )

    failures = summary["failures"]
    lines += ["", f"### Başarısız vakalar ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += [
            "| ID | Kategori | Beklenen | Gözlenen | Kaynak |",
            "|---|---|---|---|---|",
        ]
        for row in failures:
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | `{row['expected']}` | "
                f"`{row['observed']}` | `{row['source']}` |"
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
        f"| **Yanlış pozitif oranı** | **{summary['false_positive_rate']:.4f}** |",
        f"| Yanlış negatif oranı | {summary['false_negative_rate']:.4f} |",
        f"| TP={counts['true_positive']} FP={counts['false_positive']} "
        f"TN={counts['true_negative']} FN={counts['false_negative']} | |",
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | Doğruluk | FP | FN |",
        "|---|---|---|---|---|",
    ]
    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | {stats['accuracy']:.2f} | "
            f"{stats['false_positive']} | {stats['false_negative']} |"
        )

    gaps = summary["claim_detection_gaps"]
    lines += ["", f"### İddia tespiti boşlukları ({len(gaps)})", ""]
    if not gaps:
        lines.append("Yok.")
    else:
        lines += ["| ID | Kategori | Ayrıntı |", "|---|---|---|"]
        for row in gaps:
            lines.append(f"| `{row['id']}` | `{row['category']}` | {row['detail']} |")

    failures = summary["failures"]
    lines += ["", f"### Başarısız vakalar ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += [
            "| ID | Kategori | Beklenen | Gözlenen |",
            "|---|---|---|---|",
        ]
        for row in failures:
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | `{row['expected']}` | `{row['observed']}` |"
            )
    return lines


def _format_evrak_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the evrak summary as Markdown lines.

    Maps directly onto the şartname's six-bullet list: OCR routing (1),
    field extraction (3), missing-field false positives (4), and mevzuat
    citation grounding (5). Bullets 2 (type) and 6 (summary) need a live
    model and are measured separately by
    ``scripts/evaluate_classification.py`` / ``evaluate_summarization.py``.
    """
    missing_counts = summary["missing_field_counts"]
    extraction = summary["extraction_counts"]
    citation_counts = summary["citation_grounding_counts"]
    lines = [
        "### Genel -- şartname eşlemesi",
        "",
        "| Şartname maddesi | Metrik | Değer |",
        "|---|---|---|",
        f"| 1 -- OCR/doğrudan metin yönlendirmesi | Doğruluk | {summary['ocr_routing_accuracy']:.4f} |",
        f"| 3 -- bilgi unsuru çıkarma (yalnız `sentetik`) | Doğru alan oranı | {summary['extraction_correct_rate']:.4f} |",
        f"| 4 -- eksik bilgi tespiti | **Yanlış alarm oranı** | **{summary['missing_field_false_positive_rate']:.4f}** |",
        f"| 4 -- eksik bilgi tespiti | Kaçırma oranı | {summary['missing_field_false_negative_rate']:.4f} |",
        f"| 5 -- mevzuat atfı doğrulaması | Doğruluk | {summary['citation_grounding_accuracy']:.4f} |",
        "",
        f"Vaka sayısı: {summary['cases']} · "
        f"Eksik-alan (alan, belge) çifti: TP={missing_counts['true_positive']} "
        f"FP={missing_counts['false_positive']} TN={missing_counts['true_negative']} "
        f"FN={missing_counts['false_negative']} · "
        f"Çıkarım: doğru={extraction['correct']} kaçan={extraction['missed']} "
        f"yanlış={extraction['wrong']} sahte={extraction['spurious']} · "
        f"Atıf: TP={citation_counts['true_positive']} FP={citation_counts['false_positive']} "
        f"TN={citation_counts['true_negative']} FN={citation_counts['false_negative']}",
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | OCR yönlendirme doğruluğu | Eksik-alan yanlış alarm oranı |",
        "|---|---|---|---|",
    ]

    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | {stats['ocr_routing_accuracy']:.2f} | "
            f"{stats['missing_field_false_positive_rate']:.2f} |"
        )

    failures = summary["failures"]
    lines += ["", f"### Eksik-alan kümesi uyuşmayan belgeler ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += [
            "| ID | Kategori | Beklenen eksik | Gözlenen eksik |",
            "|---|---|---|---|",
        ]
        for row in failures:
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | "
                f"`{row['expected_missing_fields']}` | `{row['observed_missing_fields']}` |"
            )
    return lines


def _format_retrieval_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the chunking-arm comparison as Markdown lines."""
    baseline = summary["baseline"]
    arms = summary["arms"]
    metric_labels = (
        ("precision_at_k", "Precision@k"),
        ("recall_at_k", "Recall@k"),
        ("hit_rate_at_k", "Hit rate@k"),
        ("mean_reciprocal_rank", "MRR"),
        ("ndcg_at_k", "nDCG@k"),
        ("mean_yok_top1_score", "Yok top-1 skoru (düşük iyi)"),
    )

    lines = [
        f"> Qdrant kullanılmaz, yerel RRF ile ölçülür (bkz. `docs/evaluation/retrieval.md`). "
        f"k={summary['k']}, baseline=`{baseline}` (production ChunkingPolicy varsayılanları).",
        "",
        "### Kollar arası karşılaştırma",
        "",
        "| Metrik | "
        + " | ".join(f"`{arm}`" + (" **(baseline)**" if arm == baseline else "") for arm in arms)
        + " |",
        "|---|" + "---|" * len(arms),
    ]
    for key, label in metric_labels:
        cells = [f"{arms[arm][key]:.4f}" for arm in arms]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "### Baseline'a göre Δ (yalnızca cevaplanabilir vakalar)",
        "",
        "| Kol | ΔPrecision@k | ΔnDCG@k | ΔMRR |",
        "|---|---|---|---|",
    ]
    for arm, deltas in summary["delta_vs_baseline"].items():
        lines.append(
            f"| `{arm}` | {deltas['precision_at_k']:+.4f} | "
            f"{deltas['ndcg_at_k']:+.4f} | {deltas['mean_reciprocal_rank']:+.4f} |"
        )

    lines += [
        "",
        "### Korpus istatistikleri",
        "",
        "| Kol | Chunk sayısı | Ort. uzunluk | p50 | p95 | Sayfa atıf oranı | Span bütünlüğü |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in arms:
        stats = arms[arm]
        lines.append(
            f"| `{arm}` | {stats['chunk_count']} | {stats['mean_chunk_length']:.0f} | "
            f"{stats['p50_chunk_length']:.0f} | {stats['p95_chunk_length']:.0f} | "
            f"{stats['page_attribution_rate']:.2f} | {stats['answer_span_intactness']:.2f} |"
        )

    lines += ["", "### Kategori kırılımı (baseline kolu)", "", "| Kategori | Vaka | P@k | nDCG@k | MRR |", "|---|---|---|---|---|"]
    for category in sorted(arms[baseline]["by_category"]):
        cat_metrics = arms[baseline]["by_category"][category]
        if cat_metrics["answerable_cases"] == 0:
            # retrieval_suite.UNANSWERABLE_CATEGORY: precision/nDCG/MRR are
            # undefined here (no gold answer_spans), not zero -- a literal
            # 0.00 in this row would read as a miss, when the row is
            # actually the mean_yok_top1_score diagnostic's territory
            # (see the overall comparison table above).
            lines.append(f"| `{category}` | {cat_metrics['cases']} | - | - | - |")
            continue
        lines.append(
            f"| `{category}` | {cat_metrics['cases']} | {cat_metrics['precision_at_k']:.2f} | "
            f"{cat_metrics['ndcg_at_k']:.2f} | {cat_metrics['mean_reciprocal_rank']:.2f} |"
        )

    return lines


def _format_trajectory_markdown(summary: dict[str, Any]) -> list[str]:
    """Render the trajectory summary as Markdown lines."""
    lines = [
        "### Genel",
        "",
        "| Metrik | Değer |",
        "|---|---|",
        f"| Vaka sayısı | {summary['cases']} |",
        f"| **Tam eşleşme oranı** | **{summary['exact_match_rate']:.4f}** |",
        f"| Ortalama edit mesafesi (node-ziyareti) | {summary['mean_edit_distance']:.4f} |",
        f"| Beklenmeyen node oranı | {summary['unexpected_node_rate']:.4f} |",
        "",
        "### Kategori kırılımı",
        "",
        "| Kategori | Vaka | Tam eşleşme | Ort. edit mesafesi |",
        "|---|---|---|---|",
    ]
    for category in sorted(summary["by_category"]):
        stats = summary["by_category"][category]
        lines.append(
            f"| `{category}` | {stats['cases']} | {stats['exact_match_rate']:.2f} | "
            f"{stats['mean_edit_distance']:.2f} |"
        )

    mismatches = summary["paused_at_mismatches"]
    lines += ["", f"### Beklenmeyen duraklama noktası ({len(mismatches)})", ""]
    if not mismatches:
        lines.append("Yok.")
    else:
        lines += ["| ID | Beklenen | Gözlenen |", "|---|---|---|"]
        for row in mismatches:
            lines.append(f"| `{row['id']}` | `{row['expected']}` | `{row['observed']}` |")

    failures = summary["failures"]
    lines += ["", f"### Başarısız vakalar ({len(failures)})", ""]
    if not failures:
        lines.append("Yok.")
    else:
        lines += [
            "| ID | Kategori | Mesaj | Beklenen dizi | Gözlenen dizi | Edit mesafesi |",
            "|---|---|---|---|---|---|",
        ]
        for row in failures:
            message = row["message"].replace("|", "\\|")
            lines.append(
                f"| `{row['id']}` | `{row['category']}` | {message} | "
                f"`{row['expected']}` | `{row['observed']}` | {row['edit_distance']} |"
            )
    return lines


def _diff_lines(suite: str, current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Render the headline deltas against a baseline report."""
    if suite == "retrieval":
        # Nested one level deeper than the other suites: the comparable
        # numbers live under each report's own baseline arm, and a report's
        # baseline arm name is itself worth surfacing if it ever changes
        # between the two runs being compared (a policy default change).
        current = current.get("arms", {}).get(current.get("baseline", ""), {})
        baseline = baseline.get("arms", {}).get(baseline.get("baseline", ""), {})
        tracked = [
            ("precision_at_k", "Precision@k", True),
            ("ndcg_at_k", "nDCG@k", True),
            ("mean_reciprocal_rank", "MRR", True),
            ("answer_span_intactness", "Span bütünlüğü", True),
        ]
    elif suite == "intents":
        tracked = [
            ("macro_f1", "Macro F1", True),
            ("accuracy_over_all", "Doğruluk (tüm vakalar)", True),
            ("abstention_rate", "Eskalasyon oranı", False),
            ("clarify_rate", "Clarify oranı", False),
            ("expected_calibration_error", "Kalibrasyon hatası", False),
        ]
    elif suite == "trajectories":
        tracked = [
            ("exact_match_rate", "Tam eşleşme oranı", True),
            ("mean_edit_distance", "Ortalama edit mesafesi", False),
            ("unexpected_node_rate", "Beklenmeyen node oranı", False),
        ]
    elif suite == "drafts":
        tracked = [
            ("accuracy", "Doğruluk", True),
            ("false_positive_rate", "Yanlış pozitif oranı", False),
            ("false_negative_rate", "Yanlış negatif oranı", False),
        ]
    else:
        tracked = [
            ("ocr_routing_accuracy", "OCR yönlendirme doğruluğu", True),
            ("extraction_correct_rate", "Doğru alan oranı", True),
            ("missing_field_false_positive_rate", "Eksik-alan yanlış alarm oranı", False),
            ("missing_field_false_negative_rate", "Eksik-alan kaçırma oranı", False),
            ("citation_grounding_accuracy", "Mevzuat atfı doğrulama doğruluğu", True),
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
        elif suite == "drafts":
            lines += _format_draft_markdown(summaries[suite])
        elif suite == "trajectories":
            lines += _format_trajectory_markdown(summaries[suite])
        elif suite == "retrieval":
            lines += _format_retrieval_markdown(summaries[suite])
        else:
            lines += _format_evrak_markdown(summaries[suite])

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
    parser.add_argument(
        "--retrieval-k",
        type=int,
        default=retrieval_suite.DEFAULT_K,
        help=(
            "Retrieval suite only: cut-off rank for every chunking arm and "
            "every rank-sensitive metric. Defaults to DraftPolicy."
            "source_chunk_count -- change this to see how sensitive the "
            "comparison is to the writer's actual retrieval budget."
        ),
    )
    args = parser.parse_args(argv)

    selected = SUITES if args.suite == "all" else (args.suite,)

    runs: dict[str, EvalRun] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for suite in selected:
        run, summary = _run_suite(
            suite, with_model=args.with_model, retrieval_k=args.retrieval_k
        )
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
        if suite == "intents":
            print(
                f"[{suite}] {summary['cases']} vaka · "
                f"macro_f1={summary['macro_f1']:.4f} "
                f"abstention={summary['abstention_rate']:.4f}"
            )
        elif suite == "drafts":
            print(
                f"[{suite}] {summary['cases']} vaka · "
                f"accuracy={summary['accuracy']:.4f} "
                f"false_positive_rate={summary['false_positive_rate']:.4f}"
            )
        elif suite == "trajectories":
            print(
                f"[{suite}] {summary['cases']} vaka · "
                f"exact_match_rate={summary['exact_match_rate']:.4f} "
                f"mean_edit_distance={summary['mean_edit_distance']:.4f}"
            )
        elif suite == "retrieval":
            baseline_metrics = summary["arms"][summary["baseline"]]
            print(
                f"[{suite}] k={summary['k']} baseline=`{summary['baseline']}` · "
                f"precision_at_k={baseline_metrics['precision_at_k']:.4f} "
                f"ndcg_at_k={baseline_metrics['ndcg_at_k']:.4f}"
            )
        else:
            print(
                f"[{suite}] {summary['cases']} vaka · "
                f"ocr_routing_accuracy={summary['ocr_routing_accuracy']:.4f} "
                f"missing_field_false_positive_rate={summary['missing_field_false_positive_rate']:.4f}"
            )

    print(f"\nRapor yazıldı:\n  {json_path}\n  {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
