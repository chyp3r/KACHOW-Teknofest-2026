"""Gelen evrak-karar-cevap vaka seti için deterministik kalite kapısı.

Canlı LLM veya MCP çağrısı yapmaz. Üretim sırasında doğrulanan kayıtların
şema, anonimleştirme, olgu korunumu ve tekrar kurallarını ikinci kez ve
toplu olarak denetler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from generate_yazisma_vaka_pilotu import (
    ALLOWED_DECISIONS,
    INCOMING_TYPE_ITIRAZ,
    MAIN_OUTPUT,
    MAIN_ROOT,
    MIN_MUST_INCLUDE,
    MIN_TRACEABLE_FACTS,
    TARGET_DECISIONS,
    _anonymization_findings,
    _chronology_validation_codes,
    _draft_citation_contract_codes,
    _institution_plausibility_codes,
    _itiraz_count_for,
    _normalized_quality_text,
    _unsupported_numeric_claim_codes,
)

REQUIRED_FIELDS = {
    "case_id",
    "incoming_document",
    "incoming_type",
    "requested_action",
    "decision",
    "decision_reason",
    "outgoing_correspondence_type",
    "required_facts",
    "missing_information",
    "expected_questions",
    "gold_draft",
    "must_include",
    "must_not_invent",
    "legal_basis",
    "evidence",
    "source_origin",
    "provenance",
    "anonymization",
    "review_status",
    "source_group",
    "dataset_split",
}
ALLOWED_INCOMING_TYPES = {
    "dilekce",
    "bilgi_edinme_basvurusu",
    "ust_yazi",
    "sikayet",
    "itiraz",
    "kurum_talebi",
    "soru_onergesi",
}
ALLOWED_OUTGOING_TYPES = {
    "ust_yazi",
    "cevap_yazisi",
    "bilgilendirme_metni",
    "diger_resmi_yazisma",
}
NEAR_DUPLICATE_THRESHOLD = 0.90
_CASE_ID = re.compile(r"^GKC-(?P<decision>[A-Z_]+)-(?P<index>\d{3})$")
_PLACEHOLDER = re.compile(r"\[[^\]\n]+\]")
_NUMBER = re.compile(r"\b\d+(?:[./:-]\d+)*\b")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Geçersiz JSONL satırı: {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"JSONL satırı nesne değil: {line_number}")
            records.append(record)
    return records


def _normalized_text(value: str) -> str:
    value = value.casefold()
    value = _PLACEHOLDER.sub("[alan]", value)
    value = _NUMBER.sub("[sayi]", value)
    value = re.sub(r"[^a-zçğıöşü\[\] ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(case: dict[str, Any]) -> set[str]:
    text = f"{case.get('incoming_document', '')} {case.get('gold_draft', '')}"
    return set(_normalized_text(text).split())


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _finding(
    findings: list[dict[str, Any]],
    *,
    case_id: str,
    code: str,
    severity: str = "error",
    detail: str = "",
) -> None:
    findings.append(
        {"case_id": case_id, "code": code, "severity": severity, "detail": detail}
    )


def _expected_itiraz(case_id: str, decision: str) -> bool | None:
    match = _CASE_ID.fullmatch(case_id)
    if not match or match.group("decision") != decision.upper():
        return None
    index = int(match.group("index"))
    spec = TARGET_DECISIONS.get(decision)
    return index <= _itiraz_count_for(spec["adet"]) if spec else None


def _validate_case(case: dict[str, Any], findings: list[dict[str, Any]]) -> None:
    case_id = str(case.get("case_id") or "<case_id-yok>")
    missing_fields = sorted(REQUIRED_FIELDS - case.keys())
    if missing_fields:
        _finding(
            findings,
            case_id=case_id,
            code="eksik_zorunlu_alan",
            detail=",".join(missing_fields),
        )
        return

    decision = case["decision"]
    if decision not in ALLOWED_DECISIONS:
        _finding(findings, case_id=case_id, code="gecersiz_decision", detail=str(decision))
    if case["incoming_type"] not in ALLOWED_INCOMING_TYPES:
        _finding(
            findings,
            case_id=case_id,
            code="gecersiz_incoming_type",
            detail=str(case["incoming_type"]),
        )
    if case["outgoing_correspondence_type"] not in ALLOWED_OUTGOING_TYPES:
        _finding(
            findings,
            case_id=case_id,
            code="gecersiz_outgoing_type",
            detail=str(case["outgoing_correspondence_type"]),
        )

    expected_itiraz = _expected_itiraz(case_id, decision)
    if expected_itiraz is None:
        _finding(findings, case_id=case_id, code="gecersiz_case_id")
    elif expected_itiraz != (case["incoming_type"] == INCOMING_TYPE_ITIRAZ):
        _finding(findings, case_id=case_id, code="itiraz_kotasi_uyusmazligi")

    text_fields = {
        "incoming_document": case["incoming_document"],
        "gold_draft": case["gold_draft"],
        "metadata": json.dumps(
            {
                key: case[key]
                for key in (
                    "requested_action",
                    "decision_reason",
                    "required_facts",
                    "missing_information",
                    "expected_questions",
                    "must_include",
                    "must_not_invent",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }
    for field, text in text_fields.items():
        if "[SİLİNMİŞTİR]" in text or "[S?L?NM" in text:
            _finding(findings, case_id=case_id, code="genel_maske_kaldi", detail=field)
        privacy = _anonymization_findings(text)
        if privacy:
            kinds = sorted({item["bulgu_turu"] for item in privacy})
            _finding(
                findings,
                case_id=case_id,
                code="pii_bulgusu",
                detail=f"{field}:{','.join(kinds)}",
            )

    draft_normalized = _normalized_quality_text(case["gold_draft"])
    incoming_normalized = _normalized_quality_text(case["incoming_document"])
    if len(case["required_facts"]) < MIN_TRACEABLE_FACTS:
        _finding(findings, case_id=case_id, code="required_facts_yetersiz")
    if len(case["must_include"]) < MIN_MUST_INCLUDE:
        _finding(findings, case_id=case_id, code="must_include_listesi_yetersiz")
    for phrase in case["must_include"]:
        if _normalized_quality_text(str(phrase)) not in draft_normalized:
            _finding(
                findings,
                case_id=case_id,
                code="must_include_eksik",
                detail=hashlib.sha256(str(phrase).encode("utf-8")).hexdigest()[:12],
            )
    for phrase in case["must_not_invent"]:
        normalized = _normalized_quality_text(str(phrase))
        if normalized and normalized in draft_normalized:
            _finding(
                findings,
                case_id=case_id,
                code="must_not_invent_ihlali",
                detail=hashlib.sha256(str(phrase).encode("utf-8")).hexdigest()[:12],
            )

    for fact in case["required_facts"]:
        if not isinstance(fact, dict) or not {"alan", "deger", "kaynak_satir"} <= fact.keys():
            _finding(findings, case_id=case_id, code="required_fact_sema_hatasi")
            continue
        value = _normalized_quality_text(str(fact["deger"]))
        source_line = _normalized_quality_text(str(fact["kaynak_satir"]))
        if value and value not in incoming_normalized:
            _finding(findings, case_id=case_id, code="olgu_gelen_evrakta_yok")
        if value and value not in draft_normalized:
            _finding(findings, case_id=case_id, code="olgu_taslagina_tasinmadi")
        if source_line and source_line not in incoming_normalized:
            _finding(findings, case_id=case_id, code="kaynak_satir_bulunamadi")

    for code in _chronology_validation_codes(
        case["incoming_document"], case["gold_draft"]
    ):
        _finding(findings, case_id=case_id, code=code)
    for code in _institution_plausibility_codes(
        case["incoming_document"], case["gold_draft"]
    ):
        _finding(findings, case_id=case_id, code=code)
    for code in _unsupported_numeric_claim_codes(
        case["incoming_document"], case["gold_draft"]
    ):
        _finding(findings, case_id=case_id, code=code)

    if decision in {"eksik_belge", "belirsiz_basvuru"}:
        if not case["missing_information"]:
            _finding(findings, case_id=case_id, code="eksik_bilgi_listesi_bos")
        if not case["expected_questions"]:
            _finding(findings, case_id=case_id, code="beklenen_soru_listesi_bos")

    for item in case["missing_information"]:
        if not isinstance(item, dict) or not {"alan", "neden"} <= item.keys():
            _finding(findings, case_id=case_id, code="missing_information_sema_hatasi")

    for legal_reference in case["legal_basis"]:
        required = {
            "type",
            "number",
            "title",
            "article",
            "verification_source",
            "verification_status",
        }
        if not isinstance(legal_reference, dict) or not required <= legal_reference.keys():
            _finding(findings, case_id=case_id, code="mevzuat_sema_hatasi")
            continue
        if legal_reference["verification_status"] != "dogrulandi":
            _finding(findings, case_id=case_id, code="mevzuat_dogrulanmamis")
        if not str(legal_reference["verification_source"]).startswith("mevzuat-mcp:"):
            _finding(findings, case_id=case_id, code="mevzuat_kaynagi_gecersiz")
    for code in _draft_citation_contract_codes(case["gold_draft"], case["legal_basis"]):
        _finding(findings, case_id=case_id, code=code)

    references = case.get("provenance", {}).get("uslup_referanslari", [])
    institution = case.get("provenance", {}).get("kurum_tahmini")
    if not institution or "[" in str(institution) or "]" in str(institution):
        _finding(findings, case_id=case_id, code="kurum_anteti_bulunamadi")
    if not references:
        _finding(findings, case_id=case_id, code="provenance_referansi_yok")
    for reference in references:
        required = {"kaynak_kart_id", "kaynak_yolu", "kaynak_sha256", "source_group"}
        if not isinstance(reference, dict) or not required <= reference.keys():
            _finding(findings, case_id=case_id, code="provenance_sema_hatasi")


def evaluate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    ids = [str(case.get("case_id") or "") for case in cases]
    for case_id, count in Counter(ids).items():
        if not case_id or count > 1:
            _finding(
                findings,
                case_id=case_id or "<case_id-yok>",
                code="tekrar_case_id",
                detail=str(count),
            )

    for case in cases:
        _validate_case(case, findings)

    exact_seen: dict[str, str] = {}
    token_sets = [_tokens(case) for case in cases]
    for index, case in enumerate(cases):
        case_id = str(case.get("case_id") or "<case_id-yok>")
        digest = hashlib.sha256(" ".join(sorted(token_sets[index])).encode("utf-8")).hexdigest()
        if digest in exact_seen:
            _finding(
                findings,
                case_id=case_id,
                code="tam_tekrar",
                detail=exact_seen[digest],
            )
        else:
            exact_seen[digest] = case_id
        for other_index in range(index):
            score = _jaccard(token_sets[index], token_sets[other_index])
            if score >= NEAR_DUPLICATE_THRESHOLD:
                _finding(
                    findings,
                    case_id=case_id,
                    code="yakin_tekrar",
                    detail=f"{cases[other_index].get('case_id')}:{score:.3f}",
                )

    decision_counts = Counter(str(case.get("decision") or "") for case in cases)
    institution_counts = Counter(
        str(case.get("provenance", {}).get("kurum_tahmini") or "bilinmiyor")
        for case in cases
    )
    severity_counts = Counter(finding["severity"] for finding in findings)
    return {
        "schema_version": 1,
        "case_count": len(cases),
        "unique_case_count": len(set(ids)),
        "decision_distribution": dict(sorted(decision_counts.items())),
        "institution_distribution": dict(sorted(institution_counts.items())),
        "finding_distribution": dict(
            sorted(Counter(finding["code"] for finding in findings).items())
        ),
        "error_count": severity_counts.get("error", 0),
        "warning_count": severity_counts.get("warning", 0),
        "gate_status": "passed" if not severity_counts.get("error", 0) else "failed",
        "findings": findings,
    }


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Vaka Kalite Raporu",
        "",
        f"- Kayıt: {report['case_count']}",
        f"- Tekil kayıt: {report['unique_case_count']}",
        f"- Hata: {report['error_count']}",
        f"- Uyarı: {report['warning_count']}",
        f"- Kapı: `{report['gate_status']}`",
        "",
        "## Karar dağılımı",
        "",
        "| Karar | Adet |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| `{decision}` | {count} |"
        for decision, count in report["decision_distribution"].items()
    )
    lines.extend(["", "## Bulgu dağılımı", "", "| Bulgu | Adet |", "| --- | ---: |"])
    if report["finding_distribution"]:
        lines.extend(
            f"| `{code}` | {count} |"
            for code, count in report["finding_distribution"].items()
        )
    else:
        lines.append("| Bulgu yok | 0 |")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=MAIN_OUTPUT)
    parser.add_argument("--json-output", type=Path, default=MAIN_ROOT / "vaka-istatistikleri.json")
    parser.add_argument("--markdown-output", type=Path, default=MAIN_ROOT / "VAKA_KALITE_RAPORU.md")
    parser.add_argument("--write", action="store_true", help="Türetilmiş JSON ve Markdown raporlarını yaz.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = evaluate_cases(load_jsonl(args.input))
    if args.write:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.markdown_output.write_text(_markdown_report(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["gate_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
