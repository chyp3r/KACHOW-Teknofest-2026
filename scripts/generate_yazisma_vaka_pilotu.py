"""Az-temsil-edilen karar türleri için pilot gelen-evrak/karar/cevap vaka üretimi.

Bkz. ``datasets/resmi_yazisma/VAKA_URETIM_PLAYBOOK.md`` (nasıl kullanılır) ve
``datasets/resmi_yazisma/GELEN_EVRAK_KARAR_CEVAP_VERI_PLANI.md`` (şema/gerekçe).

Bu betik kasıtlı olarak ``scripts/scrape_open_sources.py``'nin (OS-* serisi)
yaptığının tersini yapar: rastgele kurum/konu/cümle havuzlarından birleştirme
YOKTUR. Bunun yerine hedef karar türü başına gerçek, anonimleştirilmiş
korpus kartları few-shot örnek olarak Evren'e (``llm-large``) verilir ve
çıktı ``generate_structured`` ile bir Pydantic şemasına karşı doğrulanır.

Üretilen her vaka, yazılmadan önce aynı anonimleştirme/denetim hattından
(``prepare_resmi_yazisma_markdown.semantic_anonymize`` +
``_audit_privacy_findings``) geçirilir; otomatik-düzeltilebilir bir bulgu
kalan vaka yazılmaz. Çıktı üretim ``ornekler.jsonl``'e asla otomatik
karışmaz -- ayrı bir klasöre, ``review_status: "taslak"`` ile yazılır.

Kullanım:
    python scripts/generate_yazisma_vaka_pilotu.py --dry-run
    python scripts/generate_yazisma_vaka_pilotu.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.append(os.path.dirname(__file__))

from pydantic import BaseModel, Field  # noqa: E402

from app.ai.llms import get_llm_client  # noqa: E402
from app.core.config import settings  # noqa: E402
from prepare_resmi_yazisma_markdown import (  # noqa: E402
    CORPUS_ROOT,
    _audit_privacy_findings,
    read_text,
    semantic_anonymize,
    split_front_matter,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PILOT_ROOT = REPO_ROOT / "datasets" / "resmi_yazisma_vakalar_pilot"
PILOT_OUTPUT = PILOT_ROOT / "vakalar-taslak.jsonl"

# Aşama 0'da belirlenen açık: bu dört karar türü mevcut korpusta ya hiç
# yok ya da başka bir türle karışık etiketli. Betik yalnız bunlardan
# üretir -- zaten bol olan türlerden (bilgi_edinme, ek_belge_iletimi)
# üretmek sahte bir hacim artışı olur, çeşitlilik açığını kapatmaz.
TARGET_DECISIONS: dict[str, dict[str, Any]] = {
    "yetkisizlik": {
        "adet": 5,
        "aciklama": (
            "Başvuru, muhatap kurumun görev alanına girmiyor; başvuru "
            "sahibi doğru kuruma yönlendiriliyor. Bu, eksik belge "
            "bildiriminden FARKLI bir karardır -- burada eksik olan belge "
            "değil, yetkidir."
        ),
        # Var olan en yakın gerçek örnekler biçim/üslup referansı için
        # kullanılır; bu klasördeki kartların çoğu "eksik_belge" ile
        # karışık olsa da resmî ret/yönlendirme dilini taşır.
        "few_shot_glob": "02_cevap_yazisi/08_eksik_belge_yetkisizlik/*.md",
    },
    "belirsiz_basvuru": {
        "adet": 5,
        "aciklama": (
            "Başvuru talebi belirsiz veya çelişkili; kurum karar vermek "
            "yerine ek açıklama/bilgi talep ediyor. Cevap bir karar "
            "değil, bir sorudur."
        ),
        "few_shot_glob": "02_cevap_yazisi/03_bilgi_edinme/*.md",
    },
    "coklu_talep": {
        "adet": 5,
        "aciklama": (
            "Tek başvuru yazısında birden fazla, birbirinden bağımsız "
            "talep var; kurum her talebi ayrı ayrı sonuçlandırıyor "
            "(biri kabul, biri ret, biri yönlendirme gibi)."
        ),
        "few_shot_glob": "02_cevap_yazisi/*/*.md",
    },
    "itiraz": {
        "adet": 5,
        "aciklama": (
            "Başvuru sahibi önceki bir karara itiraz ediyor; kurum "
            "itirazı inceleyip kabul veya ret yönünde gerekçeli cevap "
            "veriyor."
        ),
        "few_shot_glob": "00_gelen_kaynaklar/bilgilendirme_metni/YARG-*.md",
    },
}

FEW_SHOT_PER_TYPE = 3
MAX_EXAMPLE_CHARS = 2200


class _GeneratedCase(BaseModel):
    """Evren'in doldurduğu alanlar -- ``case_id``/``provenance``/``split``
    gibi üretim-sonrası alanlar betik tarafından ayrıca eklenir, LLM'e
    bırakılmaz (deterministik ve izlenebilir kalsın diye)."""

    incoming_document: str = Field(description="Anonim, tam gelen evrak metni")
    incoming_type: str
    requested_action: str
    decision_reason: str = Field(description="Kararın gerekçesi, tek paragraf")
    outgoing_correspondence_type: str = Field(
        description="ust_yazi | cevap_yazisi | bilgilendirme_metni | diger_resmi_yazisma"
    )
    required_facts: list[str] = Field(
        description="Gelen evraktan taslağa taşınması gereken olgular"
    )
    missing_information: list[str] = Field(default_factory=list)
    expected_questions: list[str] = Field(default_factory=list)
    gold_draft: str = Field(description="Referans cevap taslağının tam metni")
    must_include: list[str] = Field(description="Taslakta mutlaka geçmesi gereken ifadeler")
    must_not_invent: list[str] = Field(
        description="Gelen evrakta OLMAYAN, taslağın asla üretmemesi gereken değerler"
    )
    legal_basis: list[str] = Field(
        default_factory=list, description="Genel/kamusal mevzuat referansları (madde/kanun no)"
    )
    used_person_names: list[str] = Field(
        description=(
            "incoming_document ve gold_draft içinde geçen HER kurgusal kişi "
            "adını (ad soyad, yalnız ad, yalnız soyad -- unvan/rol kelimeleri "
            "hariç) tek tek listele. Bu liste, metin yazıldıktan sonra ayrı "
            "bir anonimleştirme katmanının hangi adları maskeleyeceğini "
            "belirler -- eksik bırakılan bir ad maskelenmeden kalabilir."
        )
    )


@dataclass
class FewShotExample:
    baslik: str
    kategori: str
    body_excerpt: str


def _load_few_shots(pattern: str, count: int) -> list[FewShotExample]:
    """Gerçek, zaten anonimleştirilmiş kartlardan üslup referansı seç.

    Yalnız kalite kapısını geçmiş (``candidate``) kartlar kullanılır --
    reddedilmiş/bozuk bir kartı örnek göstermek üretimi bozar.
    """
    candidates = sorted(CORPUS_ROOT.glob(pattern))
    random.Random(42).shuffle(candidates)  # deterministik ama çeşitli seçim
    examples: list[FewShotExample] = []
    for path in candidates:
        meta, body = split_front_matter(read_text(path))
        if meta.get("rag_status") != "candidate":
            continue
        examples.append(
            FewShotExample(
                baslik=meta.get("baslik", path.stem),
                kategori=meta.get("kategori", ""),
                body_excerpt=body[:MAX_EXAMPLE_CHARS],
            )
        )
        if len(examples) >= count:
            break
    return examples


def _build_messages(decision: str, spec: dict[str, Any], examples: list[FewShotExample]) -> list[dict]:
    example_blocks = "\n\n".join(
        f"[ÜSLUP ÖRNEĞİ {i + 1} -- {ex.kategori}: {ex.baslik}]\n{ex.body_excerpt}"
        for i, ex in enumerate(examples)
    )
    system = (
        "Sen Türkçe resmî yazışma eğitim verisi üreten bir asistansın. "
        "Görevin TAMAMEN KURGUSAL bir vaka üretmektir -- gerçek bir kişiyi "
        "veya gerçek bir kurum-içi olayı ASLA kullanma, tamamen uydur.\n\n"
        "ÇOK ÖNEMLİ -- köşeli parantez yer tutucusu YAZMA: Aşağıdaki üslup "
        "örnekleri, PII'sı temizlenmiş gerçek belgelerdir; bu yüzden içlerinde "
        "``[EVRAK SAYISI]``, ``[KİŞİ ADI]`` gibi köşeli parantezli alanlar "
        "görürsün. Sen bunu TAKLİT ETME. Senin ürettiğin metin, o "
        "temizlemeden ÖNCEKİ hâle karşılık gelir: isim, tarih, evrak "
        "sayısı gibi her alana somut, akla yatkın, TAMAMEN UYDURMA bir "
        "değer yaz (ör. 'Ahmet Yıldız', '14.03.2026', 'E-2026/4521') -- "
        "hiçbir zaman köşeli parantez içinde bir yer tutucu etiketi ("
        "``[...]``) üretme. Anonimleştirme, sen bu metni yazdıktan SONRA "
        "ayrı bir işlemle otomatik yapılacak; senin işin gerçekçi ve "
        "tutarlı bir kurgu yazmak.\n\n"
        "Aşağıdaki üslup örnekleri yalnız BİÇİM ve TON referansıdır; "
        "içeriklerini kopyalama veya hafifçe değiştirerek yeniden üretme, "
        "tamamen yeni bir olay kurgula. Kamu kurumu adları için yalnız "
        "genel/gerçek kurum "
        "TÜRLERİNİ (ör. 'İlçe Kaymakamlığı', 'Sosyal Güvenlik Kurumu İl "
        "Müdürlüğü') kullan, uydurma özel isim veya sahte kanun/madde "
        "numarası üretme -- yalnız gerçekten var olduğunu bildiğin genel "
        "mevzuat referanslarını (ör. '4982 sayılı Bilgi Edinme Hakkı "
        "Kanunu') kullan, emin değilsen legal_basis'i boş bırak. "
        "must_not_invent listesine, bir taslak yazma modelinin bu vakada "
        "uydurmaya en çok eğilimli olacağı 2-4 somut değeri yaz (ör. "
        "'gerçekte belirtilmeyen bir evrak sayısı', 'gerçekte belirtilmeyen "
        "bir tarih'). used_person_names ÇOK ÖNEMLİ: incoming_document ve "
        "gold_draft'ta adı geçen HER kurgusal kişiyi (başvuran, vekil, "
        "üçüncü bir kişiden bahsederken kullandığın isim -- hepsini) eksiksiz "
        "listele; bu liste metni ayrıca maskeleyecek bir güvenlik katmanının "
        "girdisidir, unutulan bir isim maskelenmeden kalır."
    )
    user = (
        f"Hedef karar türü: {decision}\n"
        f"Vaka tanımı: {spec['aciklama']}\n\n"
        f"{example_blocks}\n\n"
        "Yukarıdaki üslup örneklerine benzer resmiyette, ama TAMAMEN YENİ "
        "bir gelen evrak + kurum kararı + cevap yazısı vakası üret. "
        "incoming_document başvuranın yazdığı evrakın tam metni olmalı; "
        "gold_draft kurumun buna verdiği resmî cevabın tam metni olmalı."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _scrub_reported_names(text: str, names: list[str]) -> str:
    """Bir öz-bildirilen kurgusal adın metinde kalan her izini maskele.

    ``semantic_anonymize``'ın isim dedektörleri (``_LABELLED_NAME``,
    ``_HONORIFIC_PERSON``, imza bloğu sezgisi...) gerçek bürokratik
    belgelere göre ayarlandı -- bunlar neredeyse hiç etiketsiz, ortasında
    üçüncü bir kişiden bahsetmez. LLM'in serbest anlatı üretimi bunu
    sıkça yapar (``"...personel Mehmet Demir'e başvurdum..."``) ve hiçbir
    etiket/bağlam sezgisi bunu yakalamaz. Bu yüzden üretim adımı kendi
    kullandığı adları (``used_person_names``) bildirir; burada o listedeki
    her ad, ``semantic_anonymize`` sonrası kalan her ham geçtiği yerde
    ayrıca maskelenir (rol-etiketli geçtiği yerler zaten doğru semantik
    yer tutucuyla değişmiş olur, bu yalnız artakalanı temizler).
    """
    for name in names:
        name = name.strip()
        if len(name) < 2:
            continue
        pattern = re.compile(
            r"\b" + re.escape(name) + r"(?:'[A-Za-zÇĞİÖŞÜçğıöşüâîû]+)?\b"
        )
        text = pattern.sub("[KİŞİ ADI]", text)
    return text


def _anonymization_findings(text: str) -> list[dict]:
    """Zaten anonimleştirilmiş/temizlenmiş metinde otomatik-düzeltilebilir
    kalan bulguları döndür (boşsa vaka güvenli demektir)."""
    findings = _audit_privacy_findings(text)
    return [f for f in findings if f["otomatik_duzeltilebilir"]]


def _case_id(decision: str, index: int) -> str:
    return f"GKC-PILOT-{decision.upper()}-{index:03d}"


async def _generate_one(decision: str, spec: dict[str, Any], index: int) -> dict[str, Any] | None:
    examples = _load_few_shots(spec["few_shot_glob"], FEW_SHOT_PER_TYPE)
    if not examples:
        print(f"  [atlandı] {decision} #{index}: üslup örneği bulunamadı ({spec['few_shot_glob']})")
        return None

    client = get_llm_client(
        provider="evren", model=settings.EVREN_LLM_LARGE_MODEL, temperature=0.8
    )
    messages = _build_messages(decision, spec, examples)
    try:
        result = await client.generate_structured(messages=messages, response_model=_GeneratedCase)
    except Exception as exc:  # keep the pilot batch auditable, not fatal
        print(f"  [hata] {decision} #{index}: {type(exc).__name__}: {exc}")
        return None

    anonymized_incoming = _scrub_reported_names(
        semantic_anonymize(result.incoming_document), result.used_person_names
    )
    anonymized_draft = _scrub_reported_names(
        semantic_anonymize(result.gold_draft), result.used_person_names
    )
    bad_incoming = _anonymization_findings(anonymized_incoming)
    bad_draft = _anonymization_findings(anonymized_draft)
    if bad_incoming or bad_draft:
        kinds = sorted({f["bulgu_turu"] for f in [*bad_incoming, *bad_draft]})
        print(f"  [reddedildi] {decision} #{index}: anonimleştirme bulgusu kaldı: {kinds}")
        return None

    case_id = _case_id(decision, index)
    source_group = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:16]
    return {
        "case_id": case_id,
        "incoming_document": anonymized_incoming,
        "incoming_type": result.incoming_type,
        "requested_action": result.requested_action,
        "decision": decision,
        "decision_reason": result.decision_reason,
        "outgoing_correspondence_type": result.outgoing_correspondence_type,
        "required_facts": result.required_facts,
        "missing_information": result.missing_information,
        "expected_questions": result.expected_questions,
        "gold_draft": anonymized_draft,
        "must_include": result.must_include,
        "must_not_invent": result.must_not_invent,
        "legal_basis": result.legal_basis,
        "source_origin": "sentetik_kurgu",
        "provenance": {
            "uretim_yontemi": "evren_llm_large_few_shot",
            "uslup_referanslari": [ex.baslik for ex in examples],
        },
        "review_status": "taslak",
        "source_group": source_group,
        "dataset_split": "n/a",
    }


async def _run(apply: bool) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for decision, spec in TARGET_DECISIONS.items():
        print(f"Üretiliyor: {decision} ({spec['adet']} vaka)")
        for index in range(1, spec["adet"] + 1):
            case = await _generate_one(decision, spec, index)
            if case:
                cases.append(case)
                preview = case["incoming_document"][:160].replace("\n", " ")
                print(f"  [tamam] {case['case_id']}: {preview}...")

    print(f"\nToplam üretilen ve denetimden geçen vaka: {len(cases)}/{sum(s['adet'] for s in TARGET_DECISIONS.values())}")

    if apply and cases:
        PILOT_ROOT.mkdir(parents=True, exist_ok=True)
        with PILOT_OUTPUT.open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"Yazıldı: {PILOT_OUTPUT.relative_to(REPO_ROOT).as_posix()}")
        print(
            "Not: bu dosya üretim ornekler.jsonl'e otomatik KARIŞMAZ. "
            "Sıradaki adım için VAKA_URETIM_PLAYBOOK.md Aşama 2/3'e bakın."
        )
    elif not apply:
        print("(--dry-run: hiçbir dosya yazılmadı)")

    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Üret ama diske yazma.")
    mode.add_argument("--apply", action="store_true", help="Üret ve vakalar-taslak.jsonl'e yaz.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not settings.EVREN_API_KEY:
        print(
            "HATA: EVREN_API_KEY tanımlı değil. Bu betik yalnız Evren "
            "(llm-large) ile çalışacak şekilde tasarlandı -- bkz. "
            "VAKA_URETIM_PLAYBOOK.md 'Ön koşullar'.",
            file=sys.stderr,
        )
        return 2
    asyncio.run(_run(apply=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
