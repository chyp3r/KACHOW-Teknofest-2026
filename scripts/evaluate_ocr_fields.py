"""Measure how many prescribed evrak fields survive OCR, per engine.

The companion to `evaluate_ocr_benchmark.py`, and the one that decides which OCR
engine we ship.

That script scores text fidelity against OCRTurk, 180 real Turkish documents --
theses, journals, central-bank reports. Excellent for asking "does this engine
read Turkish", useless for asking "can the pipeline still work afterwards",
because those documents are not correspondence: they carry no `Sayı:`, `Konu:` or
`İlgi:` side-headings at all. Running field recovery there returns 0/0 for every
engine including the ground truth, which is a statement about the corpus rather
than the engines.

Header fields only exist in evrak, so this runs against `datasets/sample/`: 12
synthetic documents carrying 62 labelled fields between them, degraded the same
way, and scored with the same `parse_labelled_fields` the compliance check uses.

A transcription that reads beautifully but loses "Sayı:" is worthless here -- the
missing-field report is the product -- and a rougher one that keeps every heading
is not.

Usage:
    python scripts/evaluate_ocr_fields.py \\
        --vision-models glm-ocr:latest deepseek-ocr frob/unlimited-ocr:q8_0
"""

import argparse
import asyncio
import os
import sys
import time
from typing import Optional

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.append(os.path.dirname(__file__))

from app.ai.compliance import parse_labelled_fields  # noqa: E402
from app.infrastructure.extractors import (  # noqa: E402
    OllamaVisionExtractor,
    TesseractExtractor,
)
from evaluate_ocr_benchmark import (  # noqa: E402
    COMPARISON_PROMPT,
    degrade,
    pages_to_pdf,
    rasterise,
)

SAMPLE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "datasets", "sample"
)


def _samples(limit: Optional[int]) -> list[tuple[str, bytes, dict]]:
    """Load the evrak corpus with the fields the parser finds in each source.

    Ground truth is the parse of the *source text*, not the JSON annotation:
    the question is what OCR loses relative to a clean read, so the reference has
    to come from the same parser the OCR output is scored with.

    Args:
        limit: Optional cap on the number of documents.

    Returns:
        Tuples of document id, PDF bytes and expected field mapping.
    """
    items = []
    for text_path in sorted(
        os.path.join(SAMPLE_DIR, name)
        for name in os.listdir(SAMPLE_DIR)
        if name.startswith("evrak_") and name.endswith(".txt")
    ):
        pdf_path = text_path.replace(".txt", ".pdf")
        if not os.path.isfile(pdf_path):
            continue
        with open(text_path, encoding="utf-8") as handle:
            expected = parse_labelled_fields(handle.read())
        with open(pdf_path, "rb") as handle:
            items.append((os.path.basename(pdf_path), handle.read(), expected))
        if limit and len(items) >= limit:
            break
    if not items:
        sys.exit(f"HATA: {SAMPLE_DIR} içinde örnek evrak bulunamadı.")
    return items


def _score(expected: dict, got: dict) -> tuple[int, int]:
    """Compare a parsed OCR result against the clean-read reference.

    Args:
        expected: Fields parsed from the source text.
        got: Fields parsed from the OCR output.

    Returns:
        How many fields were found at all, and how many matched exactly.
    """
    found = sum(1 for key in expected if key in got)
    exact = sum(
        1
        for key, value in expected.items()
        if str(got.get(key, "")).strip() == str(value).strip()
    )
    return found, exact


async def run(vision_models: list[str], prompt: str, limit: Optional[int]) -> None:
    """Score every engine's field recovery over the evrak corpus."""
    items = _samples(limit)
    total = sum(len(expected) for _, _, expected in items)

    engines = [("tesseract", TesseractExtractor())]
    engines += [
        (model, OllamaVisionExtractor(model=model, prompt=prompt))
        for model in vision_models
    ]

    scores = {name: {"found": 0, "exact": 0, "sec": 0.0} for name, _ in engines}

    print("=" * 88)
    print(f"  Evrak alan kurtarma — {len(items)} belge, {total} etiketli alan")
    print(f"  bozulma: fotokopi benzeri  |  istem: {prompt!r}")
    print("=" * 88)

    for index, (name, pdf, expected) in enumerate(items):
        # Every page degraded, then packed back into one PDF -- each engine
        # rasterises it again internally, the same multi-page loop it runs
        # in production, so a document with more than one page is actually
        # exercised instead of only ever timing/scoring page one.
        pdf_bytes = pages_to_pdf([degrade(page, seed=index) for page in rasterise(pdf)])
        line = f"  {name:14s} ({len(expected)} alan)"
        for engine_name, engine in engines:
            started = time.time()
            try:
                text = (await engine.extract(pdf_bytes, mime_type="application/pdf")).text
            except Exception:  # noqa: BLE001 - a failed engine recovers nothing
                text = ""
            scores[engine_name]["sec"] += time.time() - started
            found, exact = _score(expected, parse_labelled_fields(text))
            scores[engine_name]["found"] += found
            scores[engine_name]["exact"] += exact
            line += f" | {engine_name.split('/')[-1][:12]:12s} {found}/{len(expected)}"
        print(line, flush=True)

    print("-" * 88)
    print(f"{'motor':26s} {'bulunan':>12s} {'birebir':>12s} {'süre':>9s}")
    for engine_name, _ in engines:
        s = scores[engine_name]
        print(
            f"{engine_name:26s} {s['found']:5d}/{total:<6d} {s['exact']:5d}/{total:<6d} "
            f"{s['sec']:8.1f}s"
        )
    print(
        "\n'bulunan': alan adı çıkarılan metinde bulundu. 'birebir': değeri de "
        "kaynakla aynı. Uygunluk denetimi 'bulunan' üzerinden çalışır -- bulunmayan "
        "bir alan 'eksik bilgi' olarak raporlanır, yani OCR kaybı doğrudan yanlış "
        "uyarıya dönüşür."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bozulmuş evrak taramalarında alan kurtarma karşılaştırması."
    )
    parser.add_argument("--vision-models", nargs="+", default=["glm-ocr:latest"])
    parser.add_argument("--vision-prompt", default=COMPARISON_PROMPT)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    asyncio.run(run(args.vision_models, args.vision_prompt, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
