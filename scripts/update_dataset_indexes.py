import os
import json
import csv
import re
from pathlib import Path

# Config
DATASET_ROOT = Path(__file__).parent.parent / "datasets" / "resmi_yazisma"
ALLOWED_DIRS = ["01_ust_yazi", "02_cevap_yazisi", "03_bilgilendirme_metni", "04_diger_resmi_yazisma"]

JSONL_OUT = DATASET_ROOT / "kaynak-katalogu.jsonl"
CSV_OUT = DATASET_ROOT / "kaynak-ozeti.csv"

def parse_md_file(filepath: Path) -> dict:
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return {}

    # Extract YAML frontmatter
    yaml_match = re.search(r"^---\n(.*?)\n---", content, re.MULTILINE | re.DOTALL)
    if not yaml_match:
        return {}
    
    yaml_text = yaml_match.group(1)
    
    data = {}
    for line in yaml_text.split("\n"):
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            data[key] = val
            
    # Extract Title (first H1)
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    data["baslik"] = title_match.group(1) if title_match else "Belirtilmemiş Başlık"
    
    # Generate relative path for 'kart'
    data["kart"] = filepath.relative_to(DATASET_ROOT).as_posix()
    
    return data

def main():
    records = []
    dir_records = {} # To hold records for _indeks.csv

    for allowed in ALLOWED_DIRS:
        target_dir = DATASET_ROOT / allowed
        if not target_dir.exists():
            continue
            
        dir_records[allowed] = []

        for md_file in target_dir.rglob("*.md"):
            # skip _README.md or similar
            if md_file.name.startswith("_"):
                continue
                
            data = parse_md_file(md_file)
            if data and "id" in data:
                # Add default fields for the catalog format if not present
                record = {
                    "id": data.get("id", ""),
                    "kategori": data.get("kategori", allowed),
                    "niyet": data.get("niyet", ""),
                    "baslik": data.get("baslik", ""),
                    "kurum": data.get("kurum", ""),
                    "kaynak_url": data.get("kaynak_url", None),
                    "belge_url": data.get("belge_url", None),
                    "yerel_orijinal": data.get("yerel_orijinal", None),
                    "belge_turu": data.get("belge_turu", ""),
                    "tarih_bilgisi": data.get("tarih_bilgisi", None),
                    "sayfa": data.get("sayfa", None),
                    "erisim_tarihi": data.get("erisim_tarihi", ""),
                    "dogrulama": data.get("dogrulama", ""),
                    "rag_notu": data.get("rag_notu", ""),
                    "kart": data["kart"]
                }
                records.append(record)
                dir_records[allowed].append(record)

    # Sort records by ID
    records.sort(key=lambda x: x["id"])

    # 1. Write kaynak-katalogu.jsonl
    with open(JSONL_OUT, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            
    print(f"Generated {JSONL_OUT.name} with {len(records)} records.")

    # 2. Write kaynak-ozeti.csv
    with open(CSV_OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "kategori", "niyet", "baslik", "kurum", "belge_turu", "kart"])
        writer.writeheader()
        for r in records:
            writer.writerow({
                "id": r["id"],
                "kategori": r["kategori"],
                "niyet": r["niyet"],
                "baslik": r["baslik"],
                "kurum": r["kurum"],
                "belge_turu": r["belge_turu"],
                "kart": r["kart"]
            })
            
    print(f"Generated {CSV_OUT.name} with {len(records)} records.")

    # 3. Write _indeks.csv for each directory
    for allowed in ALLOWED_DIRS:
        if not dir_records.get(allowed):
            continue
            
        target_dir = DATASET_ROOT / allowed
        idx_path = target_dir / "_indeks.csv"
        
        # Sort dir records
        d_recs = sorted(dir_records[allowed], key=lambda x: x["id"])
        
        with open(idx_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "niyet", "baslik", "belge_turu", "dosya"])
            writer.writeheader()
            for r in d_recs:
                # the file path relative to the allowed dir
                dosya = Path(r["kart"]).name
                writer.writerow({
                    "id": r["id"],
                    "niyet": r["niyet"],
                    "baslik": r["baslik"],
                    "belge_turu": r["belge_turu"],
                    "dosya": dosya
                })
        print(f"Generated _indeks.csv for {allowed} with {len(d_recs)} records.")

if __name__ == "__main__":
    main()
