"""Proof-of-concept: a dedicated Turkish NER model vs the LLM's own `entities[]`.

Context (see issue #303): `entities`/`muhatap`/`gonderen_kurum` are NOT produced
by a separate LLM call today -- they are 3 of ~14 fields bundled into the same
single structured-output call that also does document classification and
summarization (deliberately merged to halve LLM cost, see
`app/ai/workflows/document_analysis_graph.py`'s `_build_merged_output_model`
docstring). So swapping in a dedicated NER model would NOT remove an LLM
round-trip -- the other ~11 fields still need that call. The only honest
upside a dedicated model could offer is: a smaller/cleaner schema (less risk
of the documented nested-JSON-corruption failure mode) and/or better quality
specifically on the free-text `entities` field, which is the one field
genuinely NER-shaped (`muhatap`/`gonderen_kurum` already have their own
deterministic regex-recovery path in `merge_parsed_over_model`).

This script is deliberately standalone -- NOT added to backend/requirements.txt
-- since it exists to answer a one-time "is this worth pursuing" question, not
to run in production. Uses `transformers` (already pinned in
backend/requirements-training.txt for the LoRA worker image, see
app/ai/training/lora.py's lazy-import precedent) with a Turkish-native NER
checkpoint. Run it in its own throwaway venv:

    python3 -m venv .venv-ner
    .venv-ner/bin/pip install transformers torch --index-url https://download.pytorch.org/whl/cpu
    .venv-ner/bin/python scripts/ner_poc.py

Compares against `scripts/ner_poc_reference.json`, a small pre-fetched snapshot
of the current pipeline's real `entities[]` output for a few sample documents
(fetched once via a live ClassifierAgent call inside the backend container,
since this script's own venv has no access to the `app.ai` package or Evren
credentials -- there is no formal score here, `datasets/sample/evrak_*.json`
ground truth has no `entities` key to grade against; this is a side-by-side
read for a qualitative call).
"""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_PATH = os.path.join(SCRIPT_DIR, "ner_poc_reference.json")

#: Turkish-native BERT NER checkpoint (BERTurk-based) -- chosen over a generic
#: multilingual model since the corpus is exclusively Turkish official
#: correspondence, where domain-specific casing/suffix handling matters.
CANDIDATE_MODEL = "savasy/bert-base-turkish-ner-cased"


def _load_reference() -> dict:
    if not os.path.isfile(REFERENCE_PATH):
        raise SystemExit(
            f"HATA: {REFERENCE_PATH} yok. Bu dosya, backend container'ı içinde canlı bir "
            "ClassifierAgent çağrısıyla önceden üretilmiş -- yeniden üretmek için:\n"
            "  docker compose run --rm backend python -c \"...\"  (bkz. bu script'in "
            "modül docstring'i ve issue #303)"
        )
    with open(REFERENCE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    try:
        from transformers import pipeline
    except ImportError:
        raise SystemExit(
            "HATA: transformers kurulu değil. Bu script kasıtlı olarak backend'in "
            "requirements.txt'i dışında, ayrı bir venv'de çalışır -- modül docstring'ine bakın."
        )

    reference = _load_reference()
    ner = pipeline("ner", model=CANDIDATE_MODEL, aggregation_strategy="simple")

    print("=" * 90)
    print(f"   NER PoC: {CANDIDATE_MODEL} vs mevcut LLM entities[] çıktısı")
    print("=" * 90)

    for sample_id, data in reference.items():
        llm_entities = data["entities"]
        model_entities = [
            f"{item['entity_group']}:{item['word']}" for item in ner(data["text"])
        ]

        print(f"\n{sample_id}")
        print("-" * 90)
        print(f"  LLM (entities[])        : {llm_entities}")
        print(f"  {CANDIDATE_MODEL}:")
        for item in model_entities:
            print(f"    {item}")

    print("\n" + "=" * 90)
    print("DEĞERLENDİRME (yazılı öneri -- gözlemlere göre elle güncelleyin):")
    print(
        "  - Round-trip maliyeti: dedicated NER modeli mevcut LLM çağrısının YERİNE GEÇMEZ "
        "-- document_type/summary/sayi/tarih/... için o çağrı zaten gerekli. Bu model NET "
        "YENİ bir round-trip (ek gecikme + ek altyapı), mevcut olanı azaltmaz."
    )
    print(
        "  - Kalite: yukarıdaki çıktıları karşılaştırın -- LLM'in entities[] listesi zaten "
        "kurum/kişi/tarih/sayı karışımı serbest metin; dedicated model PER/ORG/LOC gibi "
        "etiketli, daha yapılandırılmış ama muhtemelen daha dar (tarih/sayı yakalamıyor)."
    )
    print(
        "  - Önerilen sonraki adım: yalnızca LLM'in entities[] şemasını sadeleştirmek "
        "isteniyorsa (nested-JSON bozulma riskini azaltmak için) değerli olabilir -- "
        "gecikme/maliyet düşürmek için DEĞİL."
    )
    print("=" * 90)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
