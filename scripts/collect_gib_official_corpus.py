"""Collect traceable official correspondence examples from GIB's public API.

The collector intentionally keeps an immutable JSON snapshot for every selected
record and writes a derived, anonymised Markdown card into the existing corpus
taxonomy.  It is deterministic for a given API response: records are selected
by explicit rules and ordered by their public record id.

Usage:
    python scripts/collect_gib_official_corpus.py
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma"
SOURCE_ROOT = CORPUS_ROOT / "00_gelen_kaynaklar" / "gib_api"
MANIFEST_PATH = CORPUS_ROOT / "gib-resmi-kaynak-manifesti.jsonl"
API_ROOT = "https://gib.gov.tr/api/gibportal/mevzuat"
ACCESS_DATE = date(2026, 8, 17).isoformat()
MAX_CARD_CHARS = 5_700

_SPACE = re.compile(r"[ \t\f\v]+")
_BLANKS = re.compile(r"\n{3,}")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+?90\s*)?(?:\(?0?\d{3}\)?[\s.-]*)\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)")
_TCKN = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
_IBAN = re.compile(r"\bTR\d{2}(?:\s?\d){22}\b", re.I)
_LONG_NUMBER = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_ELLIPSIS = re.compile(r"(?:\.{3,}|…+)")
_OFFICIAL_NUMBER = re.compile(r"\bE-\d[\dA-Z./\[\]-]{5,}", re.I)
_ATTACHMENT_LANGUAGE = re.compile(
    r"\b(?:ekli|ekte|ilişikte|gönderilmiştir|sunulmuştur)\b", re.I
)


class _TextExtractor(HTMLParser):
    _BLOCKS = {
        "br",
        "p",
        "div",
        "tr",
        "table",
        "li",
        "ul",
        "ol",
        "h1",
        "h2",
        "h3",
        "h4",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


@dataclass(frozen=True)
class CollectionSpec:
    entity: str
    prefix: str
    kategori: str
    alt_kategori: str
    niyet: str
    target_dir: Path
    limit: int
    sort_field: str
    belge_turu: str


SPECS = (
    CollectionSpec(
        entity="genelYazilar",
        prefix="GIB-UY",
        kategori="ust_yazi",
        alt_kategori="01_ek_belge_iletimi",
        niyet="ek_belge_iletimi",
        target_dir=CORPUS_ROOT / "01_ust_yazi" / "01_ek_belge_iletimi",
        limit=55,
        sort_field="tarih",
        belge_turu="resmi_genel_yazi",
    ),
    CollectionSpec(
        entity="sirkuler",
        prefix="GIB-BM",
        kategori="bilgilendirme_metni",
        alt_kategori="04_mevzuat_hak_yukumluluk",
        niyet="mevzuat_hak_yukumluluk",
        target_dir=CORPUS_ROOT
        / "03_bilgilendirme_metni"
        / "04_mevzuat_hak_yukumluluk",
        limit=25,
        sort_field="sirkulerTarih",
        belge_turu="resmi_sirkuler",
    ),
    CollectionSpec(
        entity="icGenelge",
        prefix="GIB-DY",
        kategori="diger_resmi_yazisma",
        alt_kategori="06_koordinasyon",
        niyet="koordinasyon",
        target_dir=CORPUS_ROOT / "04_diger_resmi_yazisma" / "06_koordinasyon",
        limit=65,
        sort_field="tarih",
        belge_turu="resmi_ic_genelge",
    ),
)


def _request_json(url: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    encoded = None
    headers = {"Accept": "application/json", "User-Agent": "KACHOW-dataset-research/1.0"}
    if data is not None:
        encoded = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=encoded, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed official host
        return json.load(response)


def _fetch_list(
    entity: str, sort_field: str, *, max_records: int = 500, page_size: int = 50
) -> list[dict[str, Any]]:
    """Fetch a bounded, deterministic slice while respecting the API's 50-row cap."""
    records: list[dict[str, Any]] = []
    page = 0
    while len(records) < max_records:
        params = urllib.parse.urlencode(
            {
                "page": page,
                "size": page_size,
                "sortFieldName": sort_field,
                "sortType": "DESC",
            }
        )
        payload = _request_json(
            f"{API_ROOT}/{entity}/list?{params}", data={"status": 2, "deleted": False}
        )
        container = payload["resultContainer"]
        content = list(container.get("content") or [])
        if not content:
            break
        records.extend(content)
        page += 1
        if page >= int(container.get("totalPages") or page):
            break
    return records[:max_records]


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value or "")
    text = html.unescape(parser.text()).replace("\xa0", " ")
    lines = [_SPACE.sub(" ", line).strip() for line in text.splitlines()]
    return _BLANKS.sub("\n\n", "\n".join(line for line in lines if line)).strip()


def _semantic_ellipsis(line: str) -> str:
    folded = line.casefold()
    if "sayı" in folded or "evrak" in folded:
        placeholder = "[EVRAK SAYISI]"
    elif "ilgi" in folded or "tarih" in folded:
        placeholder = "[BAŞVURU BİLGİSİ]"
    elif any(token in folded for token in ("şirket", "kurum", "işveren", "banka", "ülke")):
        placeholder = "[KURUM ADI]"
    else:
        placeholder = "[BAŞVURUYA ÖZGÜ BİLGİ]"
    return _ELLIPSIS.sub(placeholder, line)


def _anonymise(text: str) -> tuple[str, int]:
    replacements = 0
    output: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line
        line, count = _OFFICIAL_NUMBER.subn("[EVRAK SAYISI]", line)
        replacements += count
        for pattern, placeholder in (
            (_EMAIL, "[E-POSTA]"),
            (_PHONE, "[TELEFON]"),
            (_TCKN, "[T.C. KİMLİK NO]"),
            (_IBAN, "[IBAN]"),
            (_LONG_NUMBER, "[KAYIT NUMARASI]"),
        ):
            line, count = pattern.subn(placeholder, line)
            replacements += count
        if _ELLIPSIS.search(line):
            replacements += len(_ELLIPSIS.findall(line))
            line = _semantic_ellipsis(line)
        output.append(line)
    return "\n".join(output).strip(), replacements


def _paragraphs(text: str) -> list[str]:
    # The source uses table rows and individual ``p`` elements extensively.
    # After HTML normalisation each logical paragraph is one non-empty line;
    # splitting only on blank lines would treat a long document as one giant
    # paragraph and leave nothing on either side of the compaction marker.
    return [part.strip() for part in text.splitlines() if part.strip()]


def _compact(text: str, *, max_chars: int = MAX_CARD_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    parts = _paragraphs(text)
    head: list[str] = []
    tail: list[str] = []
    head_chars = 0
    tail_chars = 0
    for part in parts:
        if head_chars + len(part) + 2 > 2_800:
            break
        head.append(part)
        head_chars += len(part) + 2
    for part in reversed(parts):
        if tail_chars + len(part) + 2 > 2_350:
            break
        tail.append(part)
        tail_chars += len(part) + 2
    tail.reverse()
    compacted = "\n\n".join(
        [*head, "[MEVZUAT ALINTILARI KISALTILMIŞTIR]", *tail]
    )
    return compacted[:max_chars].rstrip()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized[:70] or "resmi-yazi"


def _yaml(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _institution(text: str) -> str:
    for line in text.splitlines()[:18]:
        if "[" not in line and len(line) <= 100 and (
            line.endswith("Defterdarlığı") or line.endswith("Vergi Dairesi Başkanlığı")
        ):
            return line.strip()
    return "Gelir İdaresi Başkanlığı"


def _response_intent(text: str) -> tuple[str, str]:
    folded = text.casefold()
    negative = any(
        marker in folded
        for marker in (
            "mümkün bulunmamakta",
            "uygun bulunmamakta",
            "reddine karar",
            "talebinizin reddi",
            "yararlanmanız mümkün değildir",
        )
    )
    positive = any(
        marker in folded
        for marker in (
            "mümkün bulunmakta",
            "uygun bulunmakta",
            "yararlanmanız mümkündür",
            "istisna kapsamında",
        )
    )
    if negative and positive:
        return "07_ret_kismen_kabul", "ret_kismen_kabul"
    if negative:
        return "07_ret_kismen_kabul", "ret"
    return "06_olumlu_cevap", "olumlu_cevap"


def _select_response_records(items: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {"ret": [], "ret_kismen_kabul": [], "olumlu_cevap": []}
    for item in items:
        text = _html_to_text(str(item.get("description") or ""))
        if len(text) < 800:
            continue
        _, intent = _response_intent(text)
        buckets[intent].append(item)
    quotas = {"ret": 20, "ret_kismen_kabul": 15, "olumlu_cevap": 20}
    selected: list[dict[str, Any]] = []
    used: set[int] = set()
    for intent, quota in quotas.items():
        for item in buckets[intent][:quota]:
            selected.append(item)
            used.add(int(item["id"]))
    if len(selected) < limit:
        for item in items:
            if int(item["id"]) in used:
                continue
            selected.append(item)
            if len(selected) == limit:
                break
    return sorted(selected[:limit], key=lambda item: int(item["id"]))


def _select_records(spec: CollectionSpec, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quality_items = [
        item
        for item in items
        if len(_html_to_text(str(item.get("description") or ""))) >= 350
    ]
    if spec.entity == "genelYazilar":
        matching = [
            item
            for item in quality_items
            if _ATTACHMENT_LANGUAGE.search(_html_to_text(str(item.get("description") or "")))
        ]
        # Prefer explicit attachment/transmission language, then fill the quota
        # with the remaining records whose official document type is itself
        # ``Genel Yazı``.  This keeps the taxonomy factual instead of inventing
        # attachment language that is absent from the source.
        matching_ids = {int(item["id"]) for item in matching}
        selected = matching + [
            item for item in quality_items if int(item["id"]) not in matching_ids
        ]
        return sorted(selected[: spec.limit], key=lambda item: int(item["id"]))
    return sorted(quality_items[: spec.limit], key=lambda item: int(item["id"]))


def _write_card(
    *,
    spec: CollectionSpec,
    item: dict[str, Any],
    ordinal: int,
    alt_kategori: str | None = None,
    niyet: str | None = None,
) -> dict[str, Any]:
    record_id = int(item["id"])
    example_id = f"{spec.prefix}-{ordinal:03d}"
    title = str(item.get("title") or f"GİB resmî yazı {record_id}").strip()
    source_url = str(item.get("siteLink") or "").strip()
    raw_text = _html_to_text(str(item.get("description") or ""))
    anonymised, replacement_count = _anonymise(raw_text)
    body = _compact(anonymised)
    institution = _institution(body)
    actual_alt = alt_kategori or spec.alt_kategori
    actual_intent = niyet or spec.niyet
    target_dir = spec.target_dir
    if alt_kategori and spec.kategori == "cevap_yazisi":
        target_dir = CORPUS_ROOT / "02_cevap_yazisi" / alt_kategori

    source_dir = SOURCE_ROOT / spec.entity
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / f"{record_id}.json"
    source_bytes = (json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    source_path.write_bytes(source_bytes)
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()

    filename = f"{example_id}_{_slug(title)}.md"
    target_path = target_dir / filename
    relative_source = source_path.relative_to(CORPUS_ROOT).as_posix()
    metadata = {
        "id": example_id,
        "kategori": spec.kategori,
        "alt_kategori": actual_alt,
        "niyet": actual_intent,
        "baslik": title,
        "kurum": institution,
        "kaynak": source_url,
        "kaynak_url": source_url,
        "yerel_orijinal": relative_source,
        "kaynak_turu": "api_json",
        "belge_turu": spec.belge_turu,
        "erisim_tarihi": ACCESS_DATE,
        "dogrulama": "resmi_kaynaktan_indirildi_api",
        "extractor": "gib_public_api_html",
        "used_ocr": "false",
        "page_count": "1",
        "quality_score": "1.0",
        "rag_status": "candidate",
        "kaynak_kurum": institution,
        "kaynak_kayit_id": record_id,
        "kaynak_sha256": source_sha256,
        "lisans_durumu": "usage_review_required",
        "metin_kapsami": "baslik_talep_gerekce_sonuc",
        "anonimlestirme_durumu": "uygun",
        "anonimlestirilen_alan_sayisi": replacement_count,
    }
    front_matter = "\n".join(f"{key}: {_yaml(value)}" for key, value in metadata.items())
    target_path.write_text(f"---\n{front_matter}\n---\n\n{body}\n", encoding="utf-8", newline="\n")
    return {
        "id": example_id,
        "source_record_id": record_id,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "source_snapshot": relative_source,
        "target": target_path.relative_to(CORPUS_ROOT).as_posix(),
        "kategori": spec.kategori,
        "alt_kategori": actual_alt,
        "niyet": actual_intent,
        "anonimlestirilen_alan_sayisi": replacement_count,
        "char_len": len(body),
    }


def _remove_managed_outputs() -> None:
    for prefix in ("GIB-UY-", "GIB-BM-", "GIB-DY-", "GIB-CY-"):
        for path in CORPUS_ROOT.glob(f"0[1-4]_*/*/{prefix}*.md"):
            path.unlink()
    if SOURCE_ROOT.exists():
        for path in SOURCE_ROOT.glob("*/*.json"):
            path.unlink()


def main() -> int:
    _remove_managed_outputs()
    manifest: list[dict[str, Any]] = []

    for spec in SPECS:
        items = _fetch_list(spec.entity, spec.sort_field)
        selected = _select_records(spec, items)
        if len(selected) < spec.limit:
            raise RuntimeError(
                f"{spec.entity}: expected {spec.limit} suitable records, got {len(selected)}"
            )
        for ordinal, item in enumerate(selected, start=1):
            manifest.append(_write_card(spec=spec, item=item, ordinal=ordinal))

    response_spec = CollectionSpec(
        entity="ozelge",
        prefix="GIB-CY",
        kategori="cevap_yazisi",
        alt_kategori="07_ret_kismen_kabul",
        niyet="ret_kismen_kabul",
        target_dir=CORPUS_ROOT / "02_cevap_yazisi" / "07_ret_kismen_kabul",
        limit=55,
        sort_field="ozelgeTarih",
        belge_turu="resmi_anonimlestirilmis_ozelge",
    )
    response_items = _fetch_list(response_spec.entity, response_spec.sort_field)
    selected_responses = _select_response_records(response_items, response_spec.limit)
    for ordinal, item in enumerate(selected_responses, start=1):
        text = _html_to_text(str(item.get("description") or ""))
        alt_kategori, niyet = _response_intent(text)
        manifest.append(
            _write_card(
                spec=response_spec,
                item=item,
                ordinal=ordinal,
                alt_kategori=alt_kategori,
                niyet=niyet,
            )
        )

    manifest.sort(key=lambda row: row["id"])
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for row in manifest:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    by_category: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    for row in manifest:
        by_category[row["kategori"]] = by_category.get(row["kategori"], 0) + 1
        by_intent[row["niyet"]] = by_intent.get(row["niyet"], 0) + 1
    print(f"Official GIB records written: {len(manifest)}")
    print(f"By category: {json.dumps(by_category, ensure_ascii=False, sort_keys=True)}")
    print(f"By intent: {json.dumps(by_intent, ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
