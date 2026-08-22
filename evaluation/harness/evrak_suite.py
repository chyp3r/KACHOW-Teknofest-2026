"""Measures the deterministic half of Görev 1 (the incoming-document/evrak
analysis pipeline) against the evrak gold set.

Binds to three independently deterministic, LLM-free functions, mirroring
which şartname bullets they answer:

  - `app.infrastructure.extractors.base.has_pdf_text_layer` /
    `is_scanned_text_layer` -- bullet 1 (OCR vs. direct-text routing).
  - `app.ai.compliance.parse_labelled_fields` -- bullet 3 (bilgi çıkarma),
    scored only on `sentetik` cases (see below).
  - `app.ai.compliance.check_required_fields` -- bullet 4 (eksik bilgi
    tespiti), fed the *real* output of `parse_labelled_fields` rather than a
    gold-derived placeholder. This is the one design choice worth stating
    explicitly: an earlier version of this suite built the fields handed to
    `check_required_fields` directly from `expected_missing_fields` (None
    for an absent key, a placeholder for a present one) -- which made the
    check tautological, since `check_required_fields` only ever tests
    `is_blank(value)` and a gold-constructed value is blank or not by
    definition. Running the real parser closes that gap: `parsed =
    parse_labelled_fields(case text)` is independent of `check_required_fields`
    and of the hand-labelled `expected_missing_fields`, so a mismatch is a
    genuine finding -- either the parser missed a labelled field or the
    checker's rule table disagrees with the hand label -- not an artifact of
    how the fixture was built. It also means a **false alarm here is real**:
    a document whose date sits unlabelled on its own line (several real
    templates in this corpus do this) reads as compliant to a human but as
    missing to the label-only regex parser, since nothing here calls the
    LLM that would catch it in production (`merge_parsed_over_model`'s other
    half). That gap is exactly what this suite exists to surface, not a bug
    in the suite.

The judge (`suggest_mevzuat_node`, bullet 5) is scored separately by
`citation_fixture_rates` below over a small embedded fixture, not the
document-level gold set -- it is a pure function of (citation, excerpts),
not of a document's text, so it does not need one row per document.

Bullet 3 (field extraction) is scored **only on `sentetik` cases**. The 23
`gercek_tarama` cases carry no `expected_fields` -- an independently
hand-transcribed exact-value dict for 23 real documents was out of scope for
this pass (see `scripts/build_evrak_eval_set.py`'s own docstring); comparing
the parser's output to itself would be circular. Bullets 1 and 4 need no
per-field value ground truth, so both run across the full merged set.
"""

from typing import Any

from langchain_core.documents import Document

from app.ai.compliance import (
    EvrakField,
    REQUIRED_FIELD_RULES,
    check_required_fields,
    citation_support,
    parse_labelled_fields,
)
from app.core.enums.document_type import DocumentType
from app.infrastructure.extractors.base import has_pdf_text_layer, is_scanned_text_layer
from evaluation.harness.runner import REPO_ROOT, EvalCase, EvalRun, load_cases, run_cases
from evaluation.metrics import BinaryRates, binary_rates

SUITE = "evrak"
DATASET = "evrak"

#: Field keys datasets/sample/evrak_*.json's expected_fields carries but
#: REQUIRED_FIELD_RULES never checks -- excluded from the extraction score
#: the same way check_required_fields itself never sees them.
_UNSCORED_FIELDS = frozenset({"entities"})


def _predict_needs_ocr(pdf_path: str) -> bool:
    """Mirror `FallbackDocumentExtractor`'s own scan-vs-text-layer routing decision.

    Args:
        pdf_path: Path to the PDF, relative to the repo root.

    Returns:
        True when the routing logic would send this file to an OCR
        extractor: no usable embedded text layer, or a scanner-origin junk
        text layer sitting over a full-page raster (Class A).
    """
    with open(REPO_ROOT / pdf_path, "rb") as handle:
        content = handle.read()
    return not has_pdf_text_layer(content) or is_scanned_text_layer(content)


def _score_extraction(parsed: dict[str, Any], expected_fields: dict[str, Any]) -> dict[str, int]:
    """Tally the four extraction outcomes evaluate_extraction.py itself uses.

    Args:
        parsed: `parse_labelled_fields`'s output for this case.
        expected_fields: The gold `EvrakField`-shaped dict.

    Returns:
        Counts of correct/missed/wrong/spurious across every scored field.
    """
    tally = {"correct": 0, "missed": 0, "wrong": 0, "spurious": 0}
    keys = (set(expected_fields) | set(parsed)) - _UNSCORED_FIELDS
    for key in keys:
        gold = expected_fields.get(key)
        observed = parsed.get(key)
        gold_blank = gold in (None, "", [])
        observed_blank = observed in (None, "", [])
        if gold_blank and observed_blank:
            continue
        if gold_blank and not observed_blank:
            tally["spurious"] += 1
        elif not gold_blank and observed_blank:
            tally["missed"] += 1
        elif str(observed).strip() == str(gold).strip():
            tally["correct"] += 1
        else:
            tally["wrong"] += 1
    return tally


def decide(case: EvalCase) -> dict[str, Any]:
    """Run one gold-set document through the three deterministic checks.

    Args:
        case: The gold-set case.

    Returns:
        The observation dict: OCR-routing prediction, the parser's raw
        output, the missing-field set it produces, and (sentetik only) the
        extraction score.
    """
    predicted_needs_ocr = _predict_needs_ocr(case.payload["pdf_path"])

    parsed = parse_labelled_fields(case.payload["text"])
    document_type = case.payload["document_type"]
    report = check_required_fields(document_type, EvrakField(**parsed))
    observed_missing = sorted(item.key for item in report.missing_fields)

    observation: dict[str, Any] = {
        "predicted_needs_ocr": predicted_needs_ocr,
        "parsed_fields": parsed,
        "observed_missing_fields": observed_missing,
        "compliance_status": report.status.value,
    }

    expected_fields = case.expected.get("expected_fields")
    if expected_fields is not None:
        observation["extraction"] = _score_extraction(parsed, expected_fields)

    return observation


def run() -> EvalRun:
    """Run the whole evrak gold set.

    Returns:
        The completed run.
    """
    return run_cases(SUITE, DATASET, load_cases(DATASET), decide)


def ocr_routing_rates(run_result: EvalRun) -> BinaryRates:
    """Tally the OCR-vs-direct-text routing decision against the gold `scanned` flag.

    Args:
        run_result: A completed evrak run.

    Returns:
        Binary confusion counts across every case, both categories.
    """
    return binary_rates(
        [
            (bool(result.case.expected["scanned"]), bool(result.observed["predicted_needs_ocr"]))
            for result in run_result.results
        ]
    )


def missing_field_rates(run_result: EvalRun) -> BinaryRates:
    """Tally the missing-field decision per (document, rule-table key) pair.

    Per-field rather than per-document on purpose: a document with seven
    checked fields and one real miss should not register as "one wrong
    document" the same way as one with every field wrong -- and the
    false-positive rate this exists to headline (a spurious "eksik bilgi" on
    a field the document actually has) is inherently a per-field question.

    Args:
        run_result: A completed evrak run.

    Returns:
        Binary confusion counts across every (case, rule key) pair, both
        categories -- this check needs no per-field value ground truth.
    """
    pairs: list[tuple[bool, bool]] = []
    for result in run_result.results:
        expected_missing = set(result.case.expected.get("expected_missing_fields") or [])
        observed_missing = set(result.observed.get("observed_missing_fields") or [])
        try:
            document_type = DocumentType(result.case.expected["document_type"])
        except ValueError:
            document_type = DocumentType.OTHER
        rules = REQUIRED_FIELD_RULES.get(document_type, ())
        for rule in rules:
            pairs.append((rule.key in expected_missing, rule.key in observed_missing))
    return binary_rates(pairs)


def extraction_totals(run_result: EvalRun) -> dict[str, int]:
    """Sum the four extraction outcomes across every `sentetik` case.

    Args:
        run_result: A completed evrak run.

    Returns:
        Summed correct/missed/wrong/spurious counts. Empty contribution from
        `gercek_tarama` cases, which carry no `extraction` observation.
    """
    totals = {"correct": 0, "missed": 0, "wrong": 0, "spurious": 0}
    for result in run_result.results:
        for key, value in result.observed.get("extraction", {}).items():
            totals[key] += value
    return totals


def failures(run_result: EvalRun) -> list[dict[str, Any]]:
    """List documents whose missing-field set didn't match the gold label.

    Args:
        run_result: A completed evrak run.

    Returns:
        One row per case where the observed missing-field set differs from
        the expected one, most-affected category first.
    """
    rows: list[dict[str, Any]] = []
    for result in run_result.results:
        expected_missing = sorted(result.case.expected.get("expected_missing_fields") or [])
        observed_missing = result.observed.get("observed_missing_fields") or []
        if expected_missing == observed_missing:
            continue
        rows.append(
            {
                "id": result.case.id,
                "category": result.case.category,
                "expected_missing_fields": expected_missing,
                "observed_missing_fields": observed_missing,
            }
        )
    return rows


#: (citation, excerpts, expected_grounded). Includes the real fabrication
#: this filter caught on its first live run against qwen3.5:9b (evrak_04,
#: `datasets/sample/`): the model cited "Madde 3" of the Dilekçe Kanunu when
#: only Article 4's text had been retrieved -- a genuine hallucination this
#: fixture pins as a permanent regression case, not a hypothetical one.
_CITATION_FIXTURE: tuple[tuple[str, tuple[Document, ...], bool], ...] = (
    (
        "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun - Madde 4",
        (
            Document(
                page_content="MADDE 4- Dilekçede, dilekçe sahibinin adı, soyadı ve imzası bulunur.",
                metadata={"mevzuat": "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun"},
            ),
        ),
        True,
    ),
    (
        "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun - Madde 3",
        (
            Document(
                page_content="MADDE 4- Dilekçede, dilekçe sahibinin adı, soyadı ve imzası bulunur.",
                metadata={"mevzuat": "3071 sayılı Dilekçe Hakkının Kullanılmasına Dair Kanun"},
            ),
        ),
        False,
    ),
    (
        "Devlet Memurları Kanunu m.103",
        (Document(page_content="irrelevant", metadata={"mevzuat": "RYUEHY"}),),
        False,
    ),
)


def citation_fixture_rates() -> BinaryRates:
    """Score `citation_support` over the embedded fabrication fixture.

    Standalone rather than gold-set-driven, since a citation's groundedness
    is a pure function of (citation, excerpts) -- it does not need a
    document-level row the way bullets 1/3/4 do.

    Returns:
        Binary confusion counts across the fixture.
    """
    return binary_rates(
        [
            (expected_grounded, citation_support(citation, list(excerpts)).grounded)
            for citation, excerpts, expected_grounded in _CITATION_FIXTURE
        ]
    )
