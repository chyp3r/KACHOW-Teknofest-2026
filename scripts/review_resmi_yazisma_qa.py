"""Run an agent-assisted review over the deterministic 100-card QA sample.

This does not claim to be a human sign-off. It records reproducible structural,
PII, boilerplate and RAG-decision checks in the existing QA manifest so the
remaining human review queue is explicit rather than an empty spreadsheet.
"""

import argparse
import csv
import os
import sys
from typing import Any

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.append(os.path.dirname(__file__))

from app.ai.guardrails.pii import find_pii  # noqa: E402
from prepare_resmi_yazisma_markdown import split_front_matter  # noqa: E402


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_MANIFEST = os.path.join(
    REPO_ROOT, "datasets", "resmi_yazisma", "manuel-qa-manifesti.csv"
)
REQUIRED_META = ("id", "kategori", "baslik", "rag_status", "kaynak_kurum")
GENERIC_MARKERS = ("[KİŞİSEL BİLGİ]", "[SİLİNMİŞTİR]")
WEB_BOILERPLATE = ("Facebook'ta Paylaş", "Bir Cevap Yaz", "Pinterest Reddit Whatsapp")


def review_card(meta: dict[str, Any], body: str) -> list[str]:
    findings: list[str] = []
    for field in REQUIRED_META:
        if not str(meta.get(field, "")).strip():
            findings.append(f"eksik_metadata:{field}")
    for marker in GENERIC_MARKERS:
        if marker in body:
            findings.append(f"genel_maske:{marker}")
    for marker in WEB_BOILERPLATE:
        if marker.casefold() in body.casefold():
            findings.append("web_boilerplate")
            break
    pii_kinds = sorted(
        {
            finding.kind
            for finding in find_pii(body)
            if finding.confidence >= 0.80
        }
    )
    if pii_kinds:
        findings.append(f"pii:{','.join(pii_kinds)}")
    status = str(meta.get("rag_status", ""))
    reason = str(meta.get("ret_nedeni", "")).strip()
    if status in {"rejected", "reference_only"} and not reason:
        findings.append("karar_gerekcesi_eksik")
    if status in {"candidate", "approved"}:
        minimum = 160 if meta.get("kategori") == "bilgilendirme_metni" else 250
        if len(body) < minimum:
            findings.append("aday_metin_cok_kisa")
        if reason:
            findings.append("adayda_ret_gerekcesi_var")
    return findings


def review_manifest(path: str, *, review_date: str, apply: bool) -> tuple[int, int]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    passed = 0
    needs_review = 0
    for row in rows:
        card_path = os.path.join(REPO_ROOT, row["dosya"].replace("/", os.sep))
        findings: list[str]
        if not os.path.isfile(card_path):
            findings = ["dosya_bulunamadi"]
        else:
            with open(card_path, encoding="utf-8") as handle:
                meta, body = split_front_matter(handle.read())
            findings = review_card(meta, body)
        if findings:
            row["manuel_sonuc"] = "insan_incelemesi_gerekli"
            row["not"] = ";".join(findings)
            needs_review += 1
        else:
            row["manuel_sonuc"] = "agent_on_incelemesi_gecti"
            row["not"] = "metadata, karar, PII, maske ve boilerplate kontrolleri uygun"
            passed += 1
        row["inceleyen"] = "codex_agent_assisted"
        row["inceleme_tarihi"] = review_date
    if apply:
        fieldnames = list(rows[0]) if rows else []
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    return passed, needs_review


def main() -> int:
    parser = argparse.ArgumentParser(description="100 kartlık QA örneklemini ön incele.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--review-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    passed, needs_review = review_manifest(
        args.manifest, review_date=args.review_date, apply=args.apply
    )
    print(f"Agent ön incelemesi geçti: {passed}")
    print(f"İnsan incelemesi gerekiyor: {needs_review}")
    return 0 if needs_review == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
