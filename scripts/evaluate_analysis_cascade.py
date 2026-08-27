"""Compare today's analyze_node cascade against a llm-fast-first, gap-fill cascade.

`analyze_node` (app/ai/workflows/document_analysis_graph.py) tries the quality
tier (llm-large) first and only falls back to the fast tier when the quality
tier raises an exception. This script measures an experimental alternative:
try the fast tier FIRST, and escalate to the quality tier only when the fast
tier's own result is missing a required field for its classified document
type (`_extract_with_gap_fill_cascade`).

This is an END-TO-END benchmark on purpose: each `datasets/sample/evrak_*.pdf`
goes through the real extraction chain (`get_document_extractor()`) exactly
once -- since extraction is identical for both cascades, its cost is measured
once and reported separately from the two cascades' own timing, so the report
shows both "realistic total time" and "cascade-only time delta" without
paying for OCR/vision extraction twice per document.

Must run against the real Evren API (LOCAL_MODE=false) since it measures real
LLM latency and quality, not a mock:

    docker compose run --rm backend python scripts/evaluate_analysis_cascade.py --repeat 2

Metrics mirror scripts/evaluate_extraction.py's taxonomy (that script measures
extraction-only accuracy against the same corpus; this one measures the
downstream analysis-cascade choice):

    correct  : belgede var, doğru çıkarıldı
    missed   : belgede var, çıkarılamadı        -> yanlış "eksik" uyarısı
    wrong    : belgede var, farklı değer geldi
    spurious : belgede yok, yine de dolduruldu  -> gerçek eksiği gizler
"""

import argparse
import asyncio
import glob
import json
import os
import sys
import time
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.agents.classifier import ClassifierAgent  # noqa: E402
from app.ai.compliance import (  # noqa: E402
    EvrakField,
    is_blank,
    merge_parsed_over_model,
    normalize_value,
    parse_labelled_fields,
)
from app.ai.llms import get_fast_llm_client, get_llm_client  # noqa: E402
from app.ai.workflows.document_analysis_graph import (  # noqa: E402
    ANALYSIS_MAX_TOKENS,
    EVRAK_FIELD_KEYS,
    DocumentAnalysisOutput,
    _build_analysis_prompt,
    _extract_with_gap_fill_cascade,
)
from app.core.enums.document_type import DocumentType  # noqa: E402
from app.infrastructure.extractors import get_document_extractor  # noqa: E402

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "sample")
#: Fraction of the expected value's tokens that must appear in the extracted value.
MATCH_TOKEN_RATIO = 0.6

OUTCOME_CORRECT = "correct"
OUTCOME_MISSED = "missed"
OUTCOME_WRONG = "wrong"
OUTCOME_SPURIOUS = "spurious"

CASCADE_BASELINE = "baseline (llm-large first)"
CASCADE_NEW = "new (llm-fast first, gap-fill)"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="İki analiz cascade'ini doğruluk ve hız açısından kıyasla.")
    parser.add_argument("--field", action="append", help="Yalnızca belirtilen alanları raporla.")
    parser.add_argument("--repeat", type=int, default=1, help="Örnek başına, her cascade için tekrar.")
    parser.add_argument("--sample", action="append", help="Yalnızca belirtilen örnek(ler)i çalıştır (ör. evrak_03).")
    return parser.parse_args()


def _load_samples(only: list[str] | None) -> list[dict]:
    samples = []
    for json_path in sorted(glob.glob(os.path.join(SAMPLE_DIR, "evrak_*.json"))):
        sample_id = os.path.splitext(os.path.basename(json_path))[0]
        if only and sample_id not in only:
            continue
        pdf_path = json_path.replace(".json", ".pdf")
        if not os.path.isfile(pdf_path):
            continue
        with open(json_path, encoding="utf-8") as handle:
            truth = json.load(handle)
        with open(pdf_path, "rb") as handle:
            truth["pdf_bytes"] = handle.read()
        truth["pdf_path"] = pdf_path
        samples.append(truth)
    return samples


def _values_match(expected: object, actual: object) -> bool:
    """Same token-overlap comparator as scripts/evaluate_extraction.py."""
    if isinstance(expected, list) or isinstance(actual, list):
        expected_text = " ".join(map(str, expected or []))
        actual_text = " ".join(map(str, actual or []))
    else:
        expected_text, actual_text = str(expected or ""), str(actual or "")

    expected_tokens = [t for t in normalize_value(expected_text).split() if len(t) > 1]
    actual_normalized = normalize_value(actual_text)
    if not expected_tokens:
        return False
    hits = sum(1 for token in expected_tokens if token in actual_normalized)
    return hits / len(expected_tokens) >= MATCH_TOKEN_RATIO


def _score(truth: dict, extracted: dict) -> dict[str, str]:
    expected_fields = truth["expected_fields"]
    outcomes = {}
    for name in EvrakField.model_fields:
        expected = expected_fields.get(name)
        actual = extracted.get(name)
        expected_present = not is_blank(expected)
        actual_present = not is_blank(actual)

        if expected_present and not actual_present:
            outcomes[name] = OUTCOME_MISSED
        elif expected_present and actual_present:
            outcomes[name] = OUTCOME_CORRECT if _values_match(expected, actual) else OUTCOME_WRONG
        elif not expected_present and actual_present:
            outcomes[name] = OUTCOME_SPURIOUS
        # Both absent: correctly left empty, not counted either way.
    return outcomes


async def _run_baseline(agent: ClassifierAgent, prompt: str) -> tuple[DocumentType, str, dict, bool]:
    """Mirrors today's analyze_node happy path: one quality-tier call, no escalation concept."""
    result = await agent.run_structured(
        messages=prompt, response_model=DocumentAnalysisOutput, temperature=0.0, max_tokens=ANALYSIS_MAX_TOKENS
    )
    payload = result.model_dump()
    document_type = DocumentType(payload["document_type"])
    model_fields = {key: payload.get(key) for key in EVRAK_FIELD_KEYS}
    return document_type, payload["summary"], model_fields, False


async def main() -> int:
    args = _parse_args()
    samples = _load_samples(args.sample)
    if not samples:
        sys.exit(f"HATA: {SAMPLE_DIR} içinde örnek bulunamadı.")

    extractor = get_document_extractor()
    quality_client = get_llm_client()
    fast_client = get_fast_llm_client()

    print("=" * 90)
    print("   Analiz Cascade Kıyaslaması: llm-large-önce (bugünkü) vs llm-fast-önce (deney)")
    print("=" * 90)
    print(f"Örnek: {len(samples)}   Tekrar: {args.repeat}\n")

    per_field: dict[str, dict[str, dict[str, int]]] = {
        CASCADE_BASELINE: defaultdict(lambda: defaultdict(int)),
        CASCADE_NEW: defaultdict(lambda: defaultdict(int)),
    }
    doc_type_correct = {CASCADE_BASELINE: 0, CASCADE_NEW: 0}
    doc_type_total = 0
    cascade_time_total = {CASCADE_BASELINE: 0.0, CASCADE_NEW: 0.0}
    extraction_time_total = 0.0
    escalation_count = 0
    escalation_total = 0

    for sample in samples:
        extraction_started = time.perf_counter()
        extracted = await extractor.extract(
            sample["pdf_bytes"], file_name=os.path.basename(sample["pdf_path"]), mime_type="application/pdf"
        )
        extraction_elapsed = time.perf_counter() - extraction_started
        extraction_time_total += extraction_elapsed

        prompt, parsed = _build_analysis_prompt(extracted.text, extracted.used_ocr)

        print(f"  {sample['id']:12s} extraction={extraction_elapsed:5.1f}s")

        for cascade_name, run_once in (
            (CASCADE_BASELINE, lambda: _run_baseline(ClassifierAgent(quality_client), prompt)),
            (
                CASCADE_NEW,
                lambda: _extract_with_gap_fill_cascade(
                    ClassifierAgent(fast_client),
                    ClassifierAgent(quality_client),
                    prompt,
                    parsed=parsed,
                    document_text=extracted.text,
                ),
            ),
        ):
            for _ in range(args.repeat):
                started = time.perf_counter()
                try:
                    document_type, _summary, model_fields, escalated = await run_once()
                except Exception as exc:  # noqa: BLE001 -- a failed call is itself a data point
                    print(f"    [{cascade_name}] HATA: {exc!r}")
                    continue
                elapsed = time.perf_counter() - started
                cascade_time_total[cascade_name] += elapsed

                if cascade_name == CASCADE_NEW:
                    escalation_total += 1
                    if escalated:
                        escalation_count += 1

                merged = merge_parsed_over_model(model_fields, parsed, document_text=extracted.text)
                outcomes = _score(sample, merged)
                for name, outcome in outcomes.items():
                    per_field[cascade_name][name][outcome] += 1

                expected_type = sample.get("document_type")
                if expected_type is not None:
                    if cascade_name == CASCADE_BASELINE:
                        doc_type_total += 1
                    if document_type.value == expected_type:
                        doc_type_correct[cascade_name] += 1

                tag = " (yükseltildi)" if cascade_name == CASCADE_NEW and escalated else ""
                print(f"    [{cascade_name}] {elapsed:5.1f}s{tag}")

    fields = args.field or list(EvrakField.model_fields)
    for cascade_name in (CASCADE_BASELINE, CASCADE_NEW):
        print("\n" + "-" * 90)
        print(f"{cascade_name}")
        print("-" * 90)
        print(f"{'alan':20s} {'correct':>8s} {'missed':>8s} {'wrong':>8s} {'spurious':>9s}  {'recall':>7s}")
        grand: dict[str, int] = defaultdict(int)
        for name in fields:
            counts = per_field[cascade_name].get(name, {})
            correct = counts.get(OUTCOME_CORRECT, 0)
            missed = counts.get(OUTCOME_MISSED, 0)
            wrong = counts.get(OUTCOME_WRONG, 0)
            spurious = counts.get(OUTCOME_SPURIOUS, 0)
            present = correct + missed + wrong
            recall = f"{100 * correct / present:.0f}%" if present else "-"
            for key, value in (
                (OUTCOME_CORRECT, correct),
                (OUTCOME_MISSED, missed),
                (OUTCOME_WRONG, wrong),
                (OUTCOME_SPURIOUS, spurious),
            ):
                grand[key] += value
            if present or spurious:
                print(f"{name:20s} {correct:8d} {missed:8d} {wrong:8d} {spurious:9d}  {recall:>7s}")
        present_total = grand[OUTCOME_CORRECT] + grand[OUTCOME_MISSED] + grand[OUTCOME_WRONG]
        overall_recall = 100 * grand[OUTCOME_CORRECT] / present_total if present_total else 0.0
        print("-" * 90)
        print(
            f"{'TOPLAM':20s} {grand[OUTCOME_CORRECT]:8d} {grand[OUTCOME_MISSED]:8d} "
            f"{grand[OUTCOME_WRONG]:8d} {grand[OUTCOME_SPURIOUS]:9d}  {overall_recall:6.1f}%"
        )
        doc_type_pct = 100 * doc_type_correct[cascade_name] / doc_type_total if doc_type_total else 0.0
        print(f"document_type doğruluğu: {doc_type_correct[cascade_name]}/{doc_type_total} ({doc_type_pct:.0f}%)")

    print("\n" + "=" * 90)
    print("SÜRE (yalnızca cascade -- extraction hariç, iki cascade de aynı extraction'ı paylaşır)")
    for cascade_name in (CASCADE_BASELINE, CASCADE_NEW):
        runs = len(samples) * args.repeat
        mean = cascade_time_total[cascade_name] / runs if runs else 0.0
        print(f"  {cascade_name:32s} toplam={cascade_time_total[cascade_name]:7.1f}s  ortalama={mean:5.1f}s")

    baseline_mean = cascade_time_total[CASCADE_BASELINE] / (len(samples) * args.repeat)
    new_mean = cascade_time_total[CASCADE_NEW] / (len(samples) * args.repeat)
    extraction_mean = extraction_time_total / len(samples)
    print(f"\nSÜRE (uçtan uca -- extraction dahil, kullanıcının gerçekte beklediği toplam)")
    print(f"  {CASCADE_BASELINE:32s} ortalama={extraction_mean + baseline_mean:5.1f}s")
    print(f"  {CASCADE_NEW:32s} ortalama={extraction_mean + new_mean:5.1f}s")

    escalation_pct = 100 * escalation_count / escalation_total if escalation_total else 0.0
    print(f"\nYükseltme oranı (yeni cascade): {escalation_count}/{escalation_total} ({escalation_pct:.0f}%)")

    print("\nVERDICT:")
    time_delta = new_mean - baseline_mean
    print(f"  Cascade süre farkı (yeni - bugünkü): {time_delta:+.1f}s/belge")
    print("  Doğruluk karşılaştırması için yukarıdaki TOPLAM/recall satırlarını iki cascade arasında kıyaslayın.")
    print("  Karar: plan dosyasındaki Adım 1c'ye bakın (Branch A: varsayılan yap / Branch B: buton olarak ekle).")
    print("=" * 90)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
