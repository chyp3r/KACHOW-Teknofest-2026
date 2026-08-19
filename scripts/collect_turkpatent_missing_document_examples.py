"""Extract anonymised missing-document notices from an official TÜRKPATENT bulletin."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium


REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma"
SOURCE_DIR = CORPUS_ROOT / "00_gelen_kaynaklar" / "turkpatent_bultenleri"
SOURCES = (
    {
        "path": SOURCE_DIR / "ilanen_tebligat_5.pdf",
        "url": (
            "https://webim.turkpatent.gov.tr/file/"
            "47695113-e8da-4fe3-ac11-668fd8322ee8?download=&name=5"
        ),
    },
    {
        "path": SOURCE_DIR / "ilanen_tebligat_9.pdf",
        "url": (
            "https://webim.turkpatent.gov.tr/file/"
            "a3115479-acc6-4fa9-87c0-3edeebbc5f7f?download=&name=9"
        ),
    },
)
TARGET_DIR = CORPUS_ROOT / "02_cevap_yazisi" / "08_eksik_belge_yetkisizlik"
MANIFEST_PATH = CORPUS_ROOT / "turkpatent-eksik-belge-manifesti.jsonl"
_SPLIT = re.compile(r"(?=Evrak\s+No\s*:)", re.I)
_EVRAK = re.compile(r"(Evrak\s+No\s*:)\s*[^\n]+?(?=\s+Başvuru\s+No\s*:)", re.I)
_BASVURU = re.compile(r"(Başvuru\s+No\s*:)\s*[^\n\s]+", re.I)
_ILGI_NUMBER = re.compile(r"\b\d{4}-(?:G|GE|O|OE)-\d+\b", re.I)
_APPLICATION_NUMBER = re.compile(r"\b20\d{2}/\d{4,6}\b")
_MARKA = re.compile(r"[\"“][^\"”\n]{1,140}[\"”](?=\s+ibareli)", re.I)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?90\s*)?(?:\(?0?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")
_PERSON_OR_COMPANY = re.compile(
    r"(?im)^(?:İtiraz Eden|Başvuru sahibinin adı/unvanı)\s*[:\-]?\s*.*$"
)
_ADDRESS_PAREN = re.compile(r"\([^\n()]{12,220}(?:CAD|MAH|SOK|NO:|BULVAR|İSTANBUL|ANKARA|BURSA)[^\n()]*\)", re.I)
_WHITESPACE = re.compile(r"[ \t]+")
_MISSING_SIGNAL = re.compile(
    r"(?:noksan\s+evrak|eksik\s+(?:belge|evrak|ödendi|ödeme|ücret)|"
    r"eksiklikler?\s+tespit|açıklama\s+gerektiren|eksiklik\s+tamamla|"
    r"tescil\s+ücreti\s+ödemesinin)",
    re.I,
)


def _read_pages(source_path: Path) -> list[str]:
    document = pdfium.PdfDocument(source_path.read_bytes())
    pages: list[str] = []
    try:
        for page in document:
            text_page = page.get_textpage()
            try:
                pages.append(text_page.get_text_range())
            finally:
                text_page.close()
                page.close()
    finally:
        document.close()
    return pages


def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line and line != "2. EVRAK İÇERİKLERİ").strip()


def _anonymise(text: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in (
        (_EVRAK, r"\1 [EVRAK SAYISI] "),
        (_BASVURU, r"\1 [BAŞVURU NUMARASI]"),
        (_ILGI_NUMBER, "[İLGİ EVRAK SAYISI]"),
        (_APPLICATION_NUMBER, "[BAŞVURU NUMARASI]"),
        (_MARKA, "[MARKA ADI]"),
        (_EMAIL, "[E-POSTA]"),
        (_PHONE, "[TELEFON]"),
        (_PERSON_OR_COMPANY, "[KİŞİ/KURUM ADI]"),
        (_ADDRESS_PAREN, "([ADRES])"),
    ):
        text, replacements = pattern.subn(replacement, text)
        count += replacements
    text = re.sub(
        r"(?i)(başvuru sahibinin adı/unvanı\s*)[\"“]?[^\n.]{2,100}",
        r"\1[KİŞİ/KURUM ADI]",
        text,
    )
    text = re.sub(r"(?i)(marka sahibinin\s+)[A-ZÇĞİÖŞÜ][^\n,.]{2,100}", r"\1[KİŞİ/KURUM ADI]", text)
    return text.strip(), count


def _scenario(text: str) -> str:
    folded = text.casefold()
    if "marka örne" in folded or "okunaklı değildir" in folded:
        return "eksik_marka_ornegi"
    if "adı/unvanı" in folded or "gerçek kişi olmadığı" in folded:
        return "eksik_basvuru_sahibi_bilgisi"
    if "eşya liste" in folded or "mal ya da mal grubu" in folded:
        return "eksik_mal_hizmet_aciklamasi"
    if "eksik ödendi" in folded or "tescil ücreti" in folded or "ödeme" in folded:
        return "eksik_ucret_bildirimi"
    if "vekaletname" in folded:
        return "eksik_vekaletname"
    return "eksik_belge_bildirimi"


def _fingerprint(text: str) -> str:
    normalized = text.casefold()
    normalized = re.sub(r"\[[^\]]+\]", "[alan]", normalized)
    normalized = re.sub(r"\d+", "[sayi]", normalized)
    normalized = re.sub(r"[^a-zçğıöşü\[\] ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract(
    source_path: Path,
    source_url: str,
    source_sha256: str,
    seen: set[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page_number, page in enumerate(_read_pages(source_path), start=1):
        for segment in _SPLIT.split(page):
            if not re.match(r"Evrak\s+No\s*:", segment.strip(), re.I):
                continue
            cleaned = _clean_text(segment)
            if len(cleaned) < 250 or not _MISSING_SIGNAL.search(cleaned):
                continue
            anonymised, replacement_count = _anonymise(cleaned)
            fingerprint = _fingerprint(anonymised)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            candidates.append(
                {
                    "page": page_number,
                    "text": anonymised[:5_900].rstrip(),
                    "scenario": _scenario(anonymised),
                    "replacement_count": replacement_count,
                    "fingerprint": fingerprint,
                    "source_path": source_path,
                    "source_url": source_url,
                    "source_sha256": source_sha256,
                }
            )
    return candidates


def _yaml(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _write_card(record: dict[str, Any], ordinal: int) -> dict[str, Any]:
    example_id = f"TP-CY-{ordinal:03d}"
    scenario = record["scenario"]
    titles = {
        "eksik_mal_hizmet_aciklamasi": "Eksik Mal veya Hizmet Açıklaması",
        "eksik_marka_ornegi": "Eksik Marka Örneği",
        "eksik_basvuru_sahibi_bilgisi": "Eksik Başvuru Sahibi Bilgisi",
        "eksik_vekaletname": "Eksik Vekâletname Bildirimi",
        "eksik_ucret_bildirimi": "Eksik Ücret Bildirimi",
        "eksik_belge_bildirimi": "Eksik Belge Bildirimi",
    }
    title = titles[scenario]
    target = TARGET_DIR / f"{example_id}_{scenario}.md"
    metadata = {
        "id": example_id,
        "kategori": "cevap_yazisi",
        "alt_kategori": "08_eksik_belge_yetkisizlik",
        "niyet": "eksik_belge_yetkisizlik",
        "baslik": title,
        "kurum": "Türk Patent ve Marka Kurumu",
        "kaynak": record["source_url"],
        "kaynak_url": record["source_url"],
        "yerel_orijinal": record["source_path"].relative_to(CORPUS_ROOT).as_posix(),
        "kaynak_turu": "pdf",
        "belge_turu": "resmi_ilanen_tebligat_bildirimi",
        "erisim_tarihi": "2026-08-17",
        "dogrulama": "resmi_kaynaktan_indirildi",
        "extractor": "pdfium_notice_splitter",
        "used_ocr": "false",
        "page_count": "1",
        "kaynak_sayfa": record["page"],
        "quality_score": "1.0",
        "rag_status": "candidate",
        "kaynak_kurum": "Türk Patent ve Marka Kurumu",
        "kaynak_sha256": record["source_sha256"],
        "lisans_durumu": "usage_review_required",
        "anonimlestirme_durumu": "uygun",
        "anonimlestirilen_alan_sayisi": record["replacement_count"],
    }
    front_matter = "\n".join(f"{key}: {_yaml(value)}" for key, value in metadata.items())
    target.write_text(
        f"---\n{front_matter}\n---\n\n{record['text']}\n", encoding="utf-8", newline="\n"
    )
    return {
        "id": example_id,
        "page": record["page"],
        "scenario": scenario,
        "source_url": record["source_url"],
        "source_sha256": record["source_sha256"],
        "source_file": record["source_path"].name,
        "target": target.relative_to(CORPUS_ROOT).as_posix(),
        "char_len": len(record["text"]),
        "anonimlestirilen_alan_sayisi": record["replacement_count"],
    }


def main() -> int:
    for source in SOURCES:
        if not source["path"].is_file():
            raise FileNotFoundError(source["path"])
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for stale in TARGET_DIR.glob("TP-CY-*.md"):
        stale.unlink()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in SOURCES:
        source_path = source["path"]
        source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        records.extend(
            _extract(source_path, source["url"], source_sha256, seen)
        )
    manifest = [_write_card(record, index) for index, record in enumerate(records, 1)]
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for row in manifest:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    scenarios: dict[str, int] = {}
    for row in manifest:
        scenarios[row["scenario"]] = scenarios.get(row["scenario"], 0) + 1
    print(f"TÜRKPATENT missing-document records written: {len(manifest)}")
    print(json.dumps(scenarios, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
