"""Benchmark the extraction chain against a real Turkish document corpus.

Our own `datasets/sample/` corpus is synthetic by necessity (competition rule 6.5
forbids real public data), which leaves one question open: do results measured on
clean, machine-rendered single-column letters hold on real Turkish documents with
real typography, multi-column layouts, tables and equations?

This script answers that against the OCRTurk benchmark:

    https://github.com/metunlp/ocrturk        (arXiv:2602.03693)

The corpus is NOT redistributed with this project -- it carries no licence file,
so clone it yourself and pass its path:

    git clone https://github.com/metunlp/ocrturk /tmp/ocrturk
    python scripts/evaluate_ocr_benchmark.py --corpus /tmp/ocrturk/data --mode text
    python scripts/evaluate_ocr_benchmark.py --corpus /tmp/ocrturk/data --mode ocr
    python scripts/evaluate_ocr_benchmark.py --corpus /tmp/ocrturk/data --mode ocr-degraded

Metrics
-------
NED     normalised Levenshtein distance, LOWER better  (as in ocrturk/eval.py)
TRchar  Turkish-character similarity, HIGHER better    (as in ocrturk/eval.py)
tokF1   order-INSENSITIVE token overlap, HIGHER better

tokF1 exists because the first two are order-sensitive and a page can be
transcribed perfectly yet in a different reading order -- on a multi-column page
that alone drove NED to 0.63 and TRchar to 0.00 for output whose token overlap was
actually *better* than the competing engine's. Read NED and tokF1 together.
"""

import argparse
import asyncio
import glob
import io
import os
import random
import re
import sys
import time
from collections import Counter

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.infrastructure.extractors import (  # noqa: E402
    OllamaVisionExtractor,
    OpenDataLoaderExtractor,
    PdfiumExtractor,
    TesseractExtractor,
)

TURKISH_CHARS = set("çğıöşüÇĞİÖŞÜ")
RENDER_DPI = 300


def _require(module: str):
    try:
        return __import__(module)
    except ImportError:
        sys.exit(
            f"HATA: '{module}' gerekli. Kurulum: pip install -r backend/requirements-dev.txt"
        )


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def plain_text(markdown: str) -> str:
    """Strip markdown, HTML and LaTeX the way the OCRTurk evaluator does."""
    text = re.sub(r"```.*?```", " ", markdown, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.DOTALL)
    return re.sub(r"^\s*\|?[\s:\-|]+\|?\s*$", " ", text, flags=re.MULTILINE)


def ned(reference: str, hypothesis: str) -> float:
    """Normalised edit distance; 0.0 is a perfect match."""
    lev = _require("Levenshtein")
    a, b = _normalise(reference), _normalise(hypothesis)
    denominator = max(len(a), len(b))
    return lev.distance(a, b) / denominator if denominator else 1.0


def turkish_char_similarity(reference: str, hypothesis: str) -> float:
    """Share of Turkish-specific characters preserved; 1.0 is perfect."""
    import difflib

    a, b = _normalise(reference), _normalise(hypothesis)
    total = sum(1 for c in a if c in TURKISH_CHARS)
    if total == 0:
        return 1.0
    errors = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag in ("delete", "replace"):
            errors += sum(1 for c in a[i1:i2] if c in TURKISH_CHARS)
        if tag in ("insert", "replace"):
            errors += sum(1 for c in b[j1:j2] if c in TURKISH_CHARS)
    return max(0.0, 1.0 - errors / total)


def token_f1(reference: str, hypothesis: str) -> float:
    """Order-insensitive token overlap; answers 'were the same words read?'."""
    a = Counter(re.findall(r"\w+", _normalise(reference)))
    b = Counter(re.findall(r"\w+", _normalise(hypothesis)))
    overlap = sum((a & b).values())
    if not overlap:
        return 0.0
    precision = overlap / max(1, sum(b.values()))
    recall = overlap / max(1, sum(a.values()))
    return 2 * precision * recall / (precision + recall)


def rasterise(pdf_bytes: bytes):
    pdfium = _require("pypdfium2")
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return document[0].render(scale=RENDER_DPI / 72).to_pil()
    finally:
        document.close()


def degrade(image, seed: int):
    """Approximate a photocopied or photographed page."""
    from PIL import Image, ImageEnhance, ImageFilter

    random.seed(seed)
    image = image.convert("L").rotate(random.uniform(-1.2, 1.2), fillcolor=255)
    image = image.resize((image.width // 2, image.height // 2))
    image = image.filter(ImageFilter.GaussianBlur(0.9))
    image = ImageEnhance.Contrast(image).enhance(0.55)
    pixels = image.load()
    for _ in range(int(image.width * image.height * 0.012)):
        pixels[
            random.randrange(image.width), random.randrange(image.height)
        ] = random.choice((0, 255))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=38)
    return Image.open(io.BytesIO(buffer.getvalue()))


def to_png(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def load_corpus(corpus_dir: str, limit: int | None):
    items = []
    pattern = os.path.join(corpus_dir, "data_*")
    for directory in sorted(
        glob.glob(pattern), key=lambda p: int(p.rsplit("_", 1)[1])
    ):
        pdfs = glob.glob(os.path.join(directory, "*.pdf"))
        markdowns = glob.glob(os.path.join(directory, "*.md"))
        if not pdfs or not markdowns:
            continue
        with open(pdfs[0], "rb") as handle:
            pdf = handle.read()
        with open(markdowns[0], encoding="utf-8") as handle:
            ground_truth = plain_text(handle.read())
        items.append((os.path.basename(directory), pdf, ground_truth))
        if limit and len(items) >= limit:
            break
    if not items:
        sys.exit(f"HATA: {pattern} kalıbına uyan belge bulunamadı.")
    return items


async def run(mode: str, items) -> None:
    if mode == "text":
        engines = [
            ("opendataloader", OpenDataLoaderExtractor()),
            ("pdfium", PdfiumExtractor()),
        ]
        mime = "application/pdf"
    else:
        engines = [("tesseract", TesseractExtractor()), ("glm-ocr", OllamaVisionExtractor())]
        mime = "image/png"

    scores = {name: {"ned": [], "tr": [], "f1": [], "sec": 0.0} for name, _ in engines}
    print("=" * 84)
    print(f"  OCRTurk — mod: {mode} — {len(items)} gerçek Türkçe belge")
    print("=" * 84)

    for index, (name, pdf, ground_truth) in enumerate(items):
        if mode == "text":
            payload = pdf
        else:
            image = rasterise(pdf)
            if mode == "ocr-degraded":
                image = degrade(image, seed=index)
            payload = to_png(image)

        for engine_name, engine in engines:
            started = time.time()
            try:
                text = (await engine.extract(payload, mime_type=mime)).text
            except Exception as exc:  # noqa: BLE001 - report and continue
                print(f"   {engine_name} hata ({name}): {type(exc).__name__}")
                text = ""
            scores[engine_name]["sec"] += time.time() - started
            scores[engine_name]["ned"].append(ned(ground_truth, text))
            scores[engine_name]["tr"].append(turkish_char_similarity(ground_truth, text))
            scores[engine_name]["f1"].append(token_f1(ground_truth, text))

    print(f"{'motor':16s} {'NED↓':>8s} {'TRchar↑':>9s} {'tokF1↑':>8s} {'süre':>8s}")
    print("-" * 84)
    for engine_name, _ in engines:
        s = scores[engine_name]
        n = len(s["ned"])
        print(
            f"{engine_name:16s} {sum(s['ned'])/n:8.3f} {sum(s['tr'])/n:9.3f} "
            f"{sum(s['f1'])/n:8.3f} {s['sec']:7.0f}s"
        )
    print(
        "\nNED ve TRchar sıra duyarlıdır; çok sütunlu sayfada doğru okunmuş bir metin "
        "farklı sırada olduğu için düşük puan alabilir. tokF1 ile birlikte okuyun."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="OCRTurk üzerinde çıkarım karşılaştırması.")
    parser.add_argument("--corpus", required=True, help="OCRTurk 'data' klasörünün yolu.")
    parser.add_argument(
        "--mode",
        choices=["text", "ocr", "ocr-degraded"],
        default="text",
        help="text: born-digital çıkarım; ocr: rasterize; ocr-degraded: fotokopi benzeri.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Belge sayısını sınırla.")
    args = parser.parse_args()

    asyncio.run(run(args.mode, load_corpus(args.corpus, args.limit)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
