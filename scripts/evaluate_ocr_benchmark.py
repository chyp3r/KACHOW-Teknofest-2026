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

from app.ai.compliance import parse_labelled_fields  # noqa: E402
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


def rasterise(pdf_bytes: bytes) -> list:
    """Rasterise every page of a PDF at RENDER_DPI.

    Every page, not just the first: tesseract.py and vision.py both OCR a
    document page by page and concatenate the result, so a benchmark payload
    with only one page never exercises that loop regardless of how many
    pages the source PDF actually has, and any timing measured against it
    says nothing about a real multi-page scan.

    Args:
        pdf_bytes: Raw PDF bytes.

    Returns:
        One rendered PIL image per page, in document order.
    """
    pdfium = _require("pypdfium2")
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        return [page.render(scale=RENDER_DPI / 72).to_pil() for page in document]
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


def pages_to_pdf(images: list) -> bytes:
    """Reassemble rasterised (optionally degraded) pages into one PDF.

    Needed only for the degraded mode: degradation is a pixel-space
    transform, so it has to run on rendered images, but every extractor's
    own extract() takes a whole document -- a PDF or a single image, never a
    list of pre-rendered pages -- so the degraded pages are packed back into
    one PDF before being handed to an engine. That engine then rasterises it
    again internally, exactly as it would a real degraded scan; the only
    cost of the double rasterisation is paid once here in the benchmark, not
    in the numbers being measured for the engine itself.

    Args:
        images: Per-page PIL images, in document order.

    Returns:
        A single multi-page PDF's bytes.
    """
    buffer = io.BytesIO()
    first, rest = images[0].convert("RGB"), [img.convert("RGB") for img in images[1:]]
    first.save(buffer, format="PDF", save_all=True, append_images=rest)
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


def recovered_fields(text: str) -> int:
    """Count the prescribed header fields a transcription still yields.

    The metric that actually decides an OCR engine for this project. Character
    similarity measures how a transcription reads; this measures whether the
    pipeline can still *use* it, because `parse_labelled_fields` is what feeds
    the compliance check. A transcription that scores well on NED but loses the
    "Sayı:" side-heading is worthless downstream, and a rougher one that keeps
    every heading is not.

    On the first degraded run this separated the engines where the text metrics
    did not: Tesseract recovered 0 of 29 fields while the vision model recovered
    all 29, on output whose NED differed by far less than that suggests.

    Args:
        text: An engine's transcription.

    Returns:
        How many labelled fields the deterministic parser found.
    """
    try:
        return len(parse_labelled_fields(text))
    except Exception:  # noqa: BLE001 - a parser failure is zero fields, not a crash
        return 0


#: Prompt used for every vision model in a comparison run.
#:
#: Deliberately one prompt for all of them, and deliberately not the extractor's
#: Turkish default. Measured on a degraded page, the instruction moves the score
#: further than the model choice does: glm-ocr goes from NED 0.164 to 0.145 just
#: by switching off the Turkish wording, and deepseek-ocr goes from a total
#: failure (NED 1.000) to its best result (tokF1 0.869). Holding it constant is
#: what makes the remaining difference attributable to the model.
COMPARISON_PROMPT = "Extract all text from this document exactly as it appears."


async def run(
    mode: str, items, vision_models: list[str], vision_prompt: str
) -> None:
    if mode == "text":
        engines = [
            ("opendataloader", OpenDataLoaderExtractor()),
            ("pdfium", PdfiumExtractor()),
        ]
        mime = "application/pdf"
    else:
        # Tesseract stays in every run as the cheap baseline; the vision models
        # are whatever was asked for, so a new candidate is compared against the
        # incumbent in the *same* session rather than against a number recorded
        # on another day with another Ollama build.
        engines = [("tesseract", TesseractExtractor())]
        engines += [
            (model, OllamaVisionExtractor(model=model, prompt=vision_prompt))
            for model in vision_models
        ]
        # PDF, not a pre-rendered PNG: each engine rasterises internally (the
        # same multi-page loop it runs in production), which is what makes
        # the timing below mean anything about a real multi-page document.
        mime = "application/pdf"

    scores = {
        name: {"ned": [], "tr": [], "f1": [], "fields": 0, "sec": 0.0}
        for name, _ in engines
    }
    truth_fields = 0
    print("=" * 96)
    print(f"  OCRTurk — mod: {mode} — {len(items)} gerçek Türkçe belge")
    if mode != "text":
        print(f"  görsel modeller: {', '.join(vision_models) or '(yok)'}")
        print(f"  ortak istem   : {vision_prompt!r}")
    print("=" * 96)

    for index, (name, pdf, ground_truth) in enumerate(items):
        if mode == "ocr-degraded":
            # Degradation is a pixel-space transform, so it has to run on
            # rendered pages -- rasterised and degraded once per document,
            # then packed back into one PDF and handed to every engine, so
            # the degradation (seeded per index) is identical across engines
            # by construction rather than by re-deriving it per engine.
            pages = [degrade(page, seed=index) for page in rasterise(pdf)]
            payload = pages_to_pdf(pages)
        else:
            # "text" mode wants the PDF as-is; "ocr" mode also just wants the
            # PDF -- each engine rasterises every page itself, the same loop
            # it runs in production, so there is nothing to prepare here.
            payload = pdf

        truth_fields += recovered_fields(ground_truth)

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
            scores[engine_name]["fields"] += recovered_fields(text)

    print(
        f"{'motor':24s} {'NED↓':>8s} {'TRchar↑':>9s} {'tokF1↑':>8s} "
        f"{'alan↑':>10s} {'süre':>9s}"
    )
    print("-" * 96)
    for engine_name, _ in engines:
        s = scores[engine_name]
        n = len(s["ned"])
        print(
            f"{engine_name:24s} {sum(s['ned'])/n:8.3f} {sum(s['tr'])/n:9.3f} "
            f"{sum(s['f1'])/n:8.3f} {s['fields']:6d}/{truth_fields:<3d} {s['sec']:8.0f}s"
        )
    print(
        "\nNED ve TRchar sıra duyarlıdır; çok sütunlu sayfada doğru okunmuş bir metin "
        "farklı sırada olduğu için düşük puan alabilir. tokF1 ile birlikte okuyun."
        "\n'alan' sütunu, çıkarılan metinden deterministik ayrıştırıcının kurtarabildiği "
        "etiketli alan sayısıdır (payda: aynı ayrıştırıcının referans metinden "
        "bulduğu alan sayısı). Uygunluk denetimini besleyen ölçüt budur."
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
    parser.add_argument(
        "--vision-models",
        nargs="+",
        default=["glm-ocr:latest"],
        help=(
            "Karşılaştırılacak Ollama görsel model etiketleri "
            "(örn. glm-ocr:latest frob/unlimited-ocr:q8_0 deepseek-ocr). "
            "Yalnızca ocr/ocr-degraded modlarında kullanılır."
        ),
    )
    parser.add_argument(
        "--vision-prompt",
        default=COMPARISON_PROMPT,
        help="Tüm görsel modellere verilen ortak istem (karşılaştırmayı adil tutar).",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            args.mode,
            load_corpus(args.corpus, args.limit),
            args.vision_models,
            args.vision_prompt,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
