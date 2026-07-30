"""Measure document-type classification accuracy over the synthetic dataset.

Classification is the load-bearing step for missing-field detection: `document_type`
selects which required-field rule table is applied, so a misclassification silently
checks the wrong fields. This script reports per-sample and overall accuracy so
prompt or model changes can be compared against a number rather than a hunch.

Reads `datasets/sample/evrak_*.txt` (not the PDFs) so the measurement isolates the
classifier from extraction quality.

Usage:
    python scripts/evaluate_classification.py
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

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "sample"
)


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
    return parser.parse_args()


def _load_samples() -> list[dict]:
    samples = []
    for json_path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "evrak_*.json"))):
        text_path = json_path.replace(".json", ".txt")
        if not os.path.isfile(text_path):
            continue
        with open(json_path, encoding="utf-8") as handle:
            truth = json.load(handle)
        with open(text_path, encoding="utf-8") as handle:
            truth["text"] = handle.read()
        samples.append(truth)
    return samples


async def main() -> int:
    args = _parse_args()
    samples = _load_samples()
    if not samples:
        sys.exit(f"HATA: {SAMPLE_DIR} içinde örnek bulunamadı.")

    # No retriever: this measures classification only, so the legislation nodes
    # would just add latency.
    graph = create_document_analysis_graph(get_llm_client(), mevzuat_retriever=None)

    print("=" * 78)
    print("   Evrak Türü Sınıflandırma Değerlendirmesi")
    print("=" * 78)
    print(f"Model      : {settings.OLLAMA_MODEL}")
    print(f"Örnek      : {len(samples)}")
    print(f"Tekrar     : {args.repeat}\n")
    print(f"{'örnek':12s} {'beklenen':22s} {'tahmin':22s} {'sonuç':6s} {'eksik alan eşleşti'}")
    print("-" * 78)

    correct = 0
    total = 0
    missing_match = 0
    started = time.time()

    for sample in samples:
        predictions = []
        missing_ok = []
        for _ in range(args.repeat):
            state = await graph.ainvoke({"input_text": sample["text"]})
            predictions.append(state.get("document_type", "?"))
            detected = sorted(
                item["key"] for item in state.get("missing_fields", [])
            )
            missing_ok.append(detected == sample["expected_missing_fields"])

        for prediction, m_ok in zip(predictions, missing_ok):
            total += 1
            correct += prediction == sample["document_type"]
            missing_match += m_ok

        stable = len(set(predictions)) == 1
        shown = predictions[0] + ("" if stable else " (kararsız)")
        mark = "OK " if predictions[0] == sample["document_type"] else "HATA"
        print(
            f"{sample['id']:12s} {sample['document_type']:22s} {shown:22s} "
            f"{mark:6s} {sum(missing_ok)}/{len(missing_ok)}"
        )

    elapsed = time.time() - started
    print("-" * 78)
    print(f"Tür doğruluğu        : {correct}/{total} ({100 * correct / total:.1f}%)")
    print(
        f"Eksik alan eşleşmesi : {missing_match}/{total} "
        f"({100 * missing_match / total:.1f}%)"
    )
    print(f"Süre                 : {elapsed:.0f} sn ({elapsed / total:.1f} sn/çalışma)")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
