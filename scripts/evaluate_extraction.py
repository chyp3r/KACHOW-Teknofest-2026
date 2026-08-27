"""Measure evrak field-extraction accuracy over the synthetic dataset.

Missing-field detection is only as good as the fields it is given. The rule table
is exact, so every end-to-end error now traces back to extraction: a field present
in the text but not extracted is reported as missing (false alarm), and a field
invented or misassigned suppresses a real finding (missed alarm).

This script scores four outcomes per field so prompt and model changes can be
compared on numbers rather than impressions:

    correct  : belgede var, doğru çıkarıldı
    missed   : belgede var, çıkarılamadı        -> yanlış "eksik" uyarısı
    wrong    : belgede var, farklı değer geldi
    spurious : belgede yok, yine de dolduruldu  -> gerçek eksiği gizler

Reads `datasets/sample/evrak_*.txt` so extraction is measured independently of PDF
parsing and OCR.

Usage:
    python scripts/evaluate_extraction.py
    OLLAMA_MODEL=qwen3:8b python scripts/evaluate_extraction.py --field sayi
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
    format_parsed_fields,
    is_blank,
    merge_parsed_over_model,
    normalize_value,
    parse_labelled_fields,
)
from app.ai.llms import get_llm_client  # noqa: E402
from app.ai.workflows.document_analysis_graph import (  # noqa: E402
    EVRAK_FIELD_KEYS,
    DocumentAnalysisOutput,
)
from app.core.config import settings  # noqa: E402

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "sample"
)
EXTRACTION_NUM_CTX = 8192
#: Fraction of the expected value's tokens that must appear in the extracted value.
MATCH_TOKEN_RATIO = 0.6

OUTCOME_CORRECT = "correct"
OUTCOME_MISSED = "missed"
OUTCOME_WRONG = "wrong"
OUTCOME_SPURIOUS = "spurious"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alan çıkarımı doğruluğunu ölç.")
    parser.add_argument(
        "--field", action="append", help="Yalnızca belirtilen alanları raporla."
    )
    parser.add_argument("--repeat", type=int, default=1, help="Örnek başına tekrar.")
    parser.add_argument(
        "--no-parser",
        action="store_true",
        help=(
            "Deterministik ayrıştırıcıyı devre dışı bırak ve yalnızca modeli ölç. "
            "Ayrıştırıcının hâlâ gerekli olup olmadığını sınamak için kullanılır."
        ),
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


def _values_match(expected: object, actual: object) -> bool:
    """Report whether an extracted value corresponds to the expected one.

    Compared on normalised tokens rather than exact strings: a model legitimately
    reformats "ÖRNEK VALİLİĞİNE" or drops a trailing label without being wrong.

    Args:
        expected: Ground-truth value.
        actual: Extracted value.

    Returns:
        True when enough of the expected tokens survive in the extracted value.
    """
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
    """Classify each field of one extraction against ground truth.

    Args:
        truth: Ground-truth record with an `expected_fields` mapping.
        extracted: The model's `EvrakField` dump.

    Returns:
        Field name to outcome.
    """
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
            outcomes[name] = (
                OUTCOME_CORRECT if _values_match(expected, actual) else OUTCOME_WRONG
            )
        elif not expected_present and actual_present:
            outcomes[name] = OUTCOME_SPURIOUS
        # Both absent: correctly left empty, not counted either way.
    return outcomes


async def main() -> int:
    args = _parse_args()
    samples = _load_samples()
    if not samples:
        sys.exit(f"HATA: {SAMPLE_DIR} içinde örnek bulunamadı.")

    agent = ClassifierAgent(get_llm_client())
    # Mirrors the production extraction node: prescribed labels are parsed
    # deterministically and the model is told to skip them.
    prompt_template = (
        "Aşağıdaki resmî evraktan üstveri alanlarını çıkar. Bir alan belgede "
        "gerçekten yoksa o alanı null bırak; tahmin etme, örnek değer üretme.\n\n"
        'EVRAK:\n"""\n{text}\n"""{note}'
    )

    print("=" * 82)
    print("   Evrak Alan Çıkarımı Değerlendirmesi")
    print("=" * 82)
    print(f"Model  : {settings.OLLAMA_MODEL}")
    print(f"Örnek  : {len(samples)}   Tekrar: {args.repeat}")
    print(f"Ayrıştırıcı: {'KAPALI (yalnızca model)' if args.no_parser else 'AÇIK'}\n")

    per_field: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_sample = []
    started = time.time()

    for sample in samples:
        totals: dict[str, int] = defaultdict(int)
        parsed = {} if args.no_parser else parse_labelled_fields(sample["text"])
        for _ in range(args.repeat):
            try:
                result = await agent.run_structured(
                    messages=prompt_template.format(
                        text=sample["text"], note=format_parsed_fields(parsed)
                    ),
                    response_model=DocumentAnalysisOutput,
                    temperature=0.0,
                    num_ctx=EXTRACTION_NUM_CTX,
                )
                payload = result.model_dump()
                model_fields = {key: payload.get(key) for key in EVRAK_FIELD_KEYS}
            except Exception:
                model_fields = EvrakField().model_dump()
            outcomes = _score(sample, merge_parsed_over_model(model_fields, parsed))
            for name, outcome in outcomes.items():
                per_field[name][outcome] += 1
                totals[outcome] += 1
        per_sample.append((sample["id"], dict(totals)))
        print(
            f"  {sample['id']:12s} correct={totals[OUTCOME_CORRECT]:2d} "
            f"missed={totals[OUTCOME_MISSED]:2d} wrong={totals[OUTCOME_WRONG]:2d} "
            f"spurious={totals[OUTCOME_SPURIOUS]:2d}"
        )

    print("\n" + "-" * 82)
    print(f"{'alan':20s} {'correct':>8s} {'missed':>8s} {'wrong':>8s} {'spurious':>9s}  {'recall':>7s}")
    print("-" * 82)
    fields = args.field or list(EvrakField.model_fields)
    grand: dict[str, int] = defaultdict(int)
    for name in fields:
        counts = per_field.get(name, {})
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
            print(
                f"{name:20s} {correct:8d} {missed:8d} {wrong:8d} {spurious:9d}  {recall:>7s}"
            )

    present_total = grand[OUTCOME_CORRECT] + grand[OUTCOME_MISSED] + grand[OUTCOME_WRONG]
    elapsed = time.time() - started
    print("-" * 82)
    print(
        f"{'TOPLAM':20s} {grand[OUTCOME_CORRECT]:8d} {grand[OUTCOME_MISSED]:8d} "
        f"{grand[OUTCOME_WRONG]:8d} {grand[OUTCOME_SPURIOUS]:9d}  "
        f"{100 * grand[OUTCOME_CORRECT] / present_total:6.1f}%"
    )
    print(
        f"\nYanlış 'eksik' uyarısına yol açan kayıp alan : {grand[OUTCOME_MISSED]}"
        f"\nGerçek eksiği gizleyebilecek uydurma alan   : {grand[OUTCOME_SPURIOUS]}"
    )
    print(f"Süre: {elapsed:.0f} sn")
    print("=" * 82)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
