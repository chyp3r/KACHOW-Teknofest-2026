"""Measure document-type classification accuracy against a live model.

Classification is the load-bearing step for missing-field detection: `document_type`
selects which required-field rule table is applied, so a misclassification silently
checks the wrong fields. This script reports per-sample and overall accuracy so
prompt or model changes can be compared against a number rather than a hunch.

Runs the *full* graph (classification, summary, missing-field detection all
included) against two corpora, distinguished throughout as `sentetik` and
`gercek_tarama` -- matching `evaluation/harness/evrak_suite.py`'s own category
names, since both draw on the same underlying documents:

  - `datasets/sample/evrak_*.txt` (12 synthetic, born-digital documents).
  - `datasets/resmi_yazisma/ocr_ground_truth.json`'s 23 hand-labelled real
    scans (`clean_text`, not the raw PDF -- this isolates classification
    from OCR quality, matching the synthetic corpus's own text-not-PDF
    reasoning above; `scripts/evaluate_ocr_real.py` is where OCR quality
    itself gets measured).

Needs a live model (şartname bullets 2 and 6 both do), so this stays a
script, not part of `evaluation/harness/` (which never calls one). Also
reports `summary` length as a cheap bullet-6 sanity signal -- not a quality
score, since there is no reference summary to compare against (see
`evaluate_summarization.py`'s own docstring on why summary quality has no
ground truth).

Usage:
    python scripts/evaluate_classification.py
    python scripts/evaluate_classification.py --corpus real
    OLLAMA_MODEL=qwen3:8b python scripts/evaluate_classification.py --repeat 3
"""

import argparse
import asyncio
import glob
import json
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.llms import get_llm_client  # noqa: E402
from app.ai.workflows.document_analysis_graph import (  # noqa: E402
    create_document_analysis_graph,
)
from app.core.config import settings  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SAMPLE_DIR = os.path.join(REPO_ROOT, "datasets", "sample")
REAL_GROUND_TRUTH = os.path.join(
    REPO_ROOT, "datasets", "resmi_yazisma", "ocr_ground_truth.json"
)
REPORT_DIR = os.path.join(REPO_ROOT, "evaluation", "reports")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evrak türü sınıflandırma doğruluğunu ölç."
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Her örneğin kaç kez çalıştırılacağı (kararlılık ölçümü için).",
    )
    parser.add_argument(
        "--corpus",
        choices=("sample", "real", "both"),
        default="both",
        help="sample: yalnız sentetik 12 örnek. real: yalnız 23 gerçek tarama. "
        "both (varsayılan): ikisi birlikte.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Sonucu evaluation/reports/<isim>.json olarak da yaz.",
    )
    return parser.parse_args()


def _load_synthetic_samples() -> list[dict]:
    samples = []
    for json_path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "evrak_*.json"))):
        text_path = json_path.replace(".json", ".txt")
        if not os.path.isfile(text_path):
            continue
        with open(json_path, encoding="utf-8") as handle:
            truth = json.load(handle)
        with open(text_path, encoding="utf-8") as handle:
            truth["text"] = handle.read()
        truth["category"] = "sentetik"
        samples.append(truth)
    return samples


def _load_real_samples() -> list[dict]:
    with open(REAL_GROUND_TRUTH, encoding="utf-8") as handle:
        ground_truth = json.load(handle)

    samples = []
    for file_name, entry in ground_truth.items():
        if file_name == "_meta":
            continue
        samples.append(
            {
                "id": file_name.split("_", 1)[0],
                "document_type": entry["document_type"],
                "text": entry["clean_text"],
                "expected_missing_fields": entry["expected_missing_fields"],
                "category": "gercek_tarama",
            }
        )
    return samples


async def main() -> int:
    args = _parse_args()
    samples: list[dict] = []
    if args.corpus in ("sample", "both"):
        samples += _load_synthetic_samples()
    if args.corpus in ("real", "both"):
        samples += _load_real_samples()
    if not samples:
        sys.exit("HATA: örnek bulunamadı.")

    # No retriever: this measures classification only, so the legislation nodes
    # would just add latency.
    graph = create_document_analysis_graph(get_llm_client(), mevzuat_retriever=None)

    print("=" * 88)
    print("   Evrak Türü Sınıflandırma Değerlendirmesi")
    print("=" * 88)
    print(f"Model      : {settings.OLLAMA_MODEL}")
    print(f"Örnek      : {len(samples)} ({args.corpus})")
    print(f"Tekrar     : {args.repeat}\n")
    print(
        f"{'örnek':12s} {'kategori':14s} {'beklenen':22s} {'tahmin':22s} "
        f"{'sonuç':6s} {'eksik alan eşleşti':10s} {'özet uzunluğu'}"
    )
    print("-" * 88)

    by_category: dict[str, dict[str, int]] = {}
    rows: list[dict] = []
    started = time.time()

    for sample in samples:
        stats = by_category.setdefault(
            sample["category"], {"correct": 0, "total": 0, "missing_match": 0}
        )
        predictions = []
        missing_ok = []
        summary_len = 0
        for _ in range(args.repeat):
            state = await graph.ainvoke({"input_text": sample["text"]})
            predictions.append(state.get("document_type", "?"))
            detected = sorted(
                item["key"] for item in state.get("missing_fields", [])
            )
            missing_ok.append(detected == sample["expected_missing_fields"])
            summary_len = len(state.get("summary", ""))

        for prediction, m_ok in zip(predictions, missing_ok):
            stats["total"] += 1
            stats["correct"] += prediction == sample["document_type"]
            stats["missing_match"] += m_ok

        stable = len(set(predictions)) == 1
        shown = predictions[0] + ("" if stable else " (kararsız)")
        mark = "OK " if predictions[0] == sample["document_type"] else "HATA"
        print(
            f"{sample['id']:12s} {sample['category']:14s} {sample['document_type']:22s} "
            f"{shown:22s} {mark:6s} {sum(missing_ok)}/{len(missing_ok):<8} {summary_len} karakter"
        )
        rows.append(
            {
                "id": sample["id"],
                "category": sample["category"],
                "expected_type": sample["document_type"],
                "predicted_type": predictions[0],
                "stable": stable,
                "missing_match": sum(missing_ok) == len(missing_ok),
                "summary_length": summary_len,
            }
        )

    elapsed = time.time() - started
    print("-" * 88)
    summary_stats = {}
    for category, stats in sorted(by_category.items()):
        accuracy = stats["correct"] / stats["total"]
        missing_rate = stats["missing_match"] / stats["total"]
        summary_stats[category] = {
            "cases": stats["total"],
            "type_accuracy": round(accuracy, 4),
            "missing_field_match_rate": round(missing_rate, 4),
        }
        print(
            f"[{category}] Tür doğruluğu: {stats['correct']}/{stats['total']} "
            f"({100 * accuracy:.1f}%) · Eksik alan eşleşmesi: "
            f"{stats['missing_match']}/{stats['total']} ({100 * missing_rate:.1f}%)"
        )

    total_cases = sum(stats["total"] for stats in by_category.values())
    print(f"Süre                 : {elapsed:.0f} sn ({elapsed / total_cases:.1f} sn/çalışma)")
    print("=" * 88)

    if args.report:
        os.makedirs(REPORT_DIR, exist_ok=True)
        report_path = os.path.join(REPORT_DIR, f"{args.report}.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "model": settings.OLLAMA_MODEL,
                    "corpus": args.corpus,
                    "repeat": args.repeat,
                    "by_category": summary_stats,
                    "elapsed_seconds": round(elapsed, 1),
                    "rows": rows,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        print(f"\nRapor yazıldı: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
