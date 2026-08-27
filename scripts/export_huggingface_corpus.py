"""HuggingFace için TÜM işlenmiş resmi_yazisma korpusunu dışa aktarır.

``curate_yazisma_examples.py``'den kasıtlı olarak AYRI: o betik projenin
kendi RAG hattı için yalnız ``rag_status: candidate`` kartları alır ve
``dilekce/`` klasörünü dışlar (gelen dilekçe, kurumun kendi yazışma üslubunu
öğretmez). Bu betik ise HuggingFace'e "işlenen tüm korpusu" (1.764 kart,
5 kategorinin tamamı, her ``rag_status`` değeri) yayınlamak için var --
projenin kendi RAG kümesi (``ornekler.jsonl``, 515 kayıt) bu betikten
etkilenmez, elle çalıştırılmadıkça hiçbir dosyaya dokunmaz.

Her kayıt kendi ``rag_status``'unu taşır: kalite kapısını geçmemiş bir
kartı "candidate" gibi göstermeyiz, yalnız hangi kartın hangi durumda
olduğunu şeffafça etiketleriz -- indirenin kendi filtrelemesini yapmasını
sağlar.

Kullanım:
    python scripts/export_huggingface_corpus.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from curate_yazisma_examples import _split_front_matter  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma"
OUT_DIR = CORPUS_ROOT / "huggingface"

#: Yalnız üretilmiş belge kartları; plan/rapor/README gibi dokümantasyon
#: dosyaları hiçbir zaman bir ``rag_status`` taşımaz, aşağıdaki filtre
#: bunları zaten otomatik eler.
_EXCLUDE_NAME_PREFIXES = ("README", "VAKA_", "GELEN_EVRAK", "RAG_VERI", "TUM_VERI")

#: Kategori isimlerini (OS-* serisinin eski klasör-adı biçimli değerleri
#: dahil) tek bir kanonik kümeye indirger -- prepare_resmi_yazisma_markdown
#: içindeki OS-* kapısı bu kartlara klasör adını (``01_ust_yazi`` gibi)
#: ``kategori`` olarak yazmıştı.
_KATEGORI_KANONIK: dict[str, str] = {
    "01_ust_yazi": "ust_yazi",
    "02_cevap_yazisi": "cevap_yazisi",
    "03_bilgilendirme_metni": "bilgilendirme_metni",
    "04_diger_resmi_yazisma": "diger_resmi_yazisma",
}


#: HuggingFace split'leri kategoriye göre ayrılır -- bir ML train/dev/heldout
#: bölünmesi değil, korpusun kendi 5 yazışma türü. Bilinmeyen bir kategori
#: (olmaması gerekir, ama fail-closed) ``diger_resmi_yazisma``'ya düşer.
_BILINEN_KATEGORILER = (
    "ust_yazi",
    "cevap_yazisi",
    "bilgilendirme_metni",
    "dilekce",
    "diger_resmi_yazisma",
)


def _iter_cards() -> list[Path]:
    cards: list[Path] = []
    for path in CORPUS_ROOT.rglob("*.md"):
        if any(path.name.startswith(prefix) for prefix in _EXCLUDE_NAME_PREFIXES):
            continue
        cards.append(path)
    return sorted(cards)


def _build_record(path: Path) -> dict[str, Any] | None:
    raw = path.read_text(encoding="utf-8")
    meta, body = _split_front_matter(raw)
    rag_status = meta.get("rag_status")
    if not rag_status:
        # rag_status taşımayan dosya bu korpusun bir "kart"ı değildir
        # (ör. kaynak-katalogu dizinindeki yardımcı dosyalar).
        return None
    kategori = _KATEGORI_KANONIK.get(meta.get("kategori", ""), meta.get("kategori", ""))
    if kategori not in _BILINEN_KATEGORILER:
        kategori = "diger_resmi_yazisma"
    source_group = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    rel_path = path.relative_to(REPO_ROOT).as_posix()
    return {
        "id": meta.get("id", path.stem),
        "kategori": kategori,
        "alt_kategori": meta.get("alt_kategori", ""),
        "niyet": meta.get("niyet", ""),
        "baslik": meta.get("baslik", ""),
        "kurum": meta.get("kurum", ""),
        "belge_turu": meta.get("belge_turu", ""),
        "rag_status": rag_status,
        "text": body,
        "char_len": len(body),
        "source_path": rel_path,
        "source_group": source_group,
    }


def main() -> int:
    records = [record for path in _iter_cards() if (record := _build_record(path)) is not None]
    print(f"Toplam kart: {len(records)}")

    by_kategori: dict[str, list[dict[str, Any]]] = {k: [] for k in _BILINEN_KATEGORILER}
    for record in records:
        by_kategori[record["kategori"]].append(record)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_path = OUT_DIR / "tumu.jsonl"
    with all_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Yazıldı: {all_path.relative_to(REPO_ROOT).as_posix()} ({len(records)})")

    for kategori, kategori_records in by_kategori.items():
        kategori_path = OUT_DIR / f"{kategori}.jsonl"
        with kategori_path.open("w", encoding="utf-8") as handle:
            for record in kategori_records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"Yazıldı: {kategori_path.relative_to(REPO_ROOT).as_posix()} ({len(kategori_records)})")

    from collections import Counter

    print("\nKategori dağılımı:")
    for kategori, count in Counter(r["kategori"] for r in records).most_common():
        print(f"  {kategori}: {count}")

    print("\nrag_status dağılımı:")
    for status, count in Counter(r["rag_status"] for r in records).most_common():
        print(f"  {status}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
