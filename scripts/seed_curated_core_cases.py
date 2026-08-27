"""LLM tekrarları yerine elle denetlenmiş çekirdek vaka eksiklerini tamamla.

Bu betik yalnız altı sabit Aşama 4 vakasını üretir. Ham korpusa ve üretim
``ornekler.jsonl`` dosyasına dokunmaz; mevcut checkpoint'e atomik ekleme yapar.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from generate_yazisma_vaka_pilotu import (
    FEW_SHOT_PER_TYPE,
    MAIN_OUTPUT,
    TARGET_DECISIONS,
    _case_template_group,
    _collect_placeholders,
    _content_validation_codes,
    _load_existing_cases,
    _load_few_shots,
    _write_jsonl_atomic,
)


def _base(
    *,
    case_id: str,
    decision: str,
    institution: str,
    incoming: str,
    requested_action: str,
    reason: str,
    draft: str,
    facts: list[dict[str, str]],
    must_include: list[str],
    must_not_invent: list[str],
    missing: list[dict[str, str]] | None = None,
    questions: list[str] | None = None,
) -> dict[str, Any]:
    spec = TARGET_DECISIONS[decision]
    examples = _load_few_shots(
        spec["few_shot_glob"],
        FEW_SHOT_PER_TYPE,
        niyet_filter=spec.get("niyet_filter"),
    )
    references = [
        {
            "kaynak_kart_id": example.card_id,
            "kaynak_yolu": example.source_path,
            "kaynak_sha256": example.card_sha256,
            "source_group": example.source_group,
        }
        for example in examples
    ]
    record: dict[str, Any] = {
        "case_id": case_id,
        "incoming_document": incoming,
        "incoming_type": "itiraz",
        "requested_action": requested_action,
        "decision": decision,
        "decision_reason": reason,
        "outgoing_correspondence_type": "cevap_yazisi",
        "required_facts": facts,
        "missing_information": missing or [],
        "expected_questions": questions or [],
        "gold_draft": draft,
        "must_include": must_include,
        "must_not_invent": must_not_invent,
        "legal_basis": [],
        "legal_basis_text": [],
        "evidence": [{**reference, "tur": "uslup_referansi"} for reference in references],
        "source_origin": "sentetik_kurgu",
        "provenance": {
            "kurum_tahmini": institution,
            "uretim_yontemi": "deterministic_curated_core",
            "uslup_referanslari": references,
        },
        "review_status": "taslak",
        "source_group": _case_template_group(incoming, draft),
        "dataset_split": "n/a",
    }
    record["anonymization"] = {
        "denetim_durumu": "uygun",
        "yer_tutucular": sorted(_collect_placeholders(record)),
        "yontem": "curated_semantic_placeholders+privacy_audit",
    }
    codes = _content_validation_codes(
        decision=decision,
        incoming_document=incoming,
        gold_draft=draft,
        required_facts=facts,
        missing_information=record["missing_information"],
        expected_questions=record["expected_questions"],
        must_include=must_include,
        must_not_invent=must_not_invent,
        legal_basis=[],
    )
    if codes:
        raise ValueError(f"{case_id}: {','.join(sorted(set(codes)))}")
    return record


def curated_cases() -> list[dict[str, Any]]:
    return [
        _base(
            case_id="GKC-RET-002",
            decision="ret",
            institution="BURSA BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI",
            incoming="""T.C.
BURSA BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI
Ulaşım Dairesi Başkanlığına

Konu: 10.02.2026 tarihli engelli park yeri talebi kararına itiraz

Apartman girişimizin önüne ikinci bir engelli park yeri ayrılması talebimin reddine itiraz ediyorum. Mevcut engelli park yeri giriş kapısından 35 metre uzaktadır ve kullanılabilir durumdadır. Bununla birlikte aracıma daha yakın ikinci bir yer ayrılmasını istiyorum.

10.02.2026 tarihli kararın kaldırılmasını arz ederim.

15.02.2026
[KİŞİ ADI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="Mevcut yere ek olarak ikinci bir engelli park yeri ayrılması.",
            reason="Başvuran, giriş kapısından 35 metre uzakta kullanılabilir bir engelli park yerinin mevcut olduğunu bildirmiştir. Aynı giriş için ikinci bir yer ayrılmasını gerektiren yeni bir ihtiyaç veya değişiklik sunulmadığından önceki karar korunmuştur.",
            draft="""T.C.
BURSA BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI
Ulaşım Dairesi Başkanlığı

Sayı: E-2026/2145
Konu: Engelli Park Yeri Talebine İtiraz
Tarih: 20.02.2026

İlgi: 15.02.2026 tarihli itiraz dilekçeniz.

İtirazınız incelenmiştir. Dilekçenizde apartman girişinden 35 metre uzakta kullanılabilir bir engelli park yerinin bulunduğunu, buna ek olarak aracınıza daha yakın ikinci bir yer ayrılmasını istediğinizi belirtmektesiniz.

Mevcut park yerinin kullanılmasını engelleyen yeni bir durum bildirilmediğinden ikinci bir engelli park yeri ayrılması talebiniz uygun bulunmamış ve 10.02.2026 tarihli karar değiştirilmemiştir. İtirazınız reddedilmiştir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
Ulaşım Dairesi Başkanı""",
            facts=[
                {"alan": "mevcut park yeri mesafesi", "deger": "35 metre", "kaynak_satir": "Mevcut engelli park yeri giriş kapısından 35 metre uzaktadır ve kullanılabilir durumdadır."}
            ],
            must_include=["İtirazınız reddedilmiştir", "35 metre"],
            must_not_invent=["sağlık raporu", "plaka numarası", "yeni bir engel oranı"],
        ),
        _base(
            case_id="GKC-KISMI_KABUL-001",
            decision="kismi_kabul",
            institution="ANKARA SU VE KANALİZASYON İDARESİ GENEL MÜDÜRLÜĞÜ",
            incoming="""T.C.
ANKARA SU VE KANALİZASYON İDARESİ GENEL MÜDÜRLÜĞÜNE

Konu: 12.02.2026 tarihli fatura itirazım

Su sayacımın endeksi 118 m³ olmasına rağmen faturada 128 m³ yazılmıştır. Endeksin 118 m³ olarak düzeltilmesini ve faturadaki sabit hizmet bedelinin de tamamen kaldırılmasını talep ediyorum. Su hizmeti bu dönemde devam etmiştir.

15.02.2026
[KİŞİ ADI]
Abone No: [ABONE NUMARASI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="Sayaç endeksinin düzeltilmesi ve sabit hizmet bedelinin kaldırılması.",
            reason="Sayaç endeksinin 118 m³ olduğu başvuru bilgisiyle uyumludur ve düzeltme talebi kabul edilmiştir. Su hizmetinin devam ettiği başvuran tarafından belirtildiğinden sabit hizmet bedelinin tamamen kaldırılması talebi reddedilmiştir.",
            draft="""T.C.
ANKARA SU VE KANALİZASYON İDARESİ GENEL MÜDÜRLÜĞÜ
Abone İşleri Dairesi Başkanlığı

Sayı: E-2026/3312
Konu: Fatura İtirazı
Tarih: 20.02.2026

İlgi: 15.02.2026 tarihli itirazınız.

İtirazınız incelenmiştir. Faturada 128 m³ olarak yer alan sayaç endeksinin 118 m³ olarak düzeltilmesi talebiniz kabul edilmiştir.

Su hizmetinin ilgili dönemde devam ettiğini belirttiğinizden sabit hizmet bedelinin tamamen kaldırılması talebiniz reddedilmiştir. Faturanız yalnız sayaç endeksi yönünden yeniden düzenlenecektir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
Abone İşleri Dairesi Başkanı""",
            facts=[
                {"alan": "doğru sayaç endeksi", "deger": "118 m³", "kaynak_satir": "Su sayacımın endeksi 118 m³ olmasına rağmen faturada 128 m³ yazılmıştır."},
                {"alan": "faturadaki endeks", "deger": "128 m³", "kaynak_satir": "Su sayacımın endeksi 118 m³ olmasına rağmen faturada 128 m³ yazılmıştır."},
            ],
            must_include=["talebiniz kabul edilmiştir", "talebiniz reddedilmiştir"],
            must_not_invent=["ödeme tarihi", "gecikme faizi", "inceleme tutanağı"],
        ),
        _base(
            case_id="GKC-EKSIK_BELGE-001",
            decision="eksik_belge",
            institution="ANKARA VALİLİĞİ",
            incoming="""T.C.
ANKARA VALİLİĞİ
İl Kültür ve Turizm Müdürlüğüne

Konu: 10.02.2026 tarihli eksik belge bildirimine itiraz

20.03.2026 tarihinde düzenlemek istediğim sergi için yaptığım başvuruda Mülk Sahibi Muvafakatnamesi istenmiştir. Bu belgeyi henüz temin edemedim ve itiraz dilekçemin ekinde de sunamıyorum. Diğer belgelerin değerlendirilmesini ve başvurumun sonuçlandırılmasını talep ediyorum.

15.02.2026
[KİŞİ ADI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="Mülk Sahibi Muvafakatnamesi olmadan sergi başvurusunun sonuçlandırılması.",
            reason="Başvuran, Mülk Sahibi Muvafakatnamesini henüz temin edemediğini ve itiraz ekinde sunamadığını açıkça bildirmiştir. Belge tamamlanmadan başvuru sonuçlandırılamaz.",
            draft="""T.C.
ANKARA VALİLİĞİ
İl Kültür ve Turizm Müdürlüğü

Sayı: E-2026/1764
Konu: Eksik Belge Bildirimi
Tarih: 20.02.2026

İlgi: 15.02.2026 tarihli itiraz dilekçeniz.

20.03.2026 tarihinde düzenlemek istediğiniz sergiye ilişkin itirazınız incelenmiştir. Dilekçenizde Mülk Sahibi Muvafakatnamesini henüz temin edemediğinizi ve itiraz ekinde sunamadığınızı belirtmektesiniz.

Başvurunuzun sonuçlandırılabilmesi için Mülk Sahibi Muvafakatnamesini Müdürlüğümüze sunmanız gerekmektedir. Belge sunulduğunda dosyanız yeniden değerlendirilecektir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
İl Kültür ve Turizm Müdürü""",
            facts=[
                {"alan": "etkinlik tarihi", "deger": "20.03.2026", "kaynak_satir": "20.03.2026 tarihinde düzenlemek istediğim sergi için yaptığım başvuruda Mülk Sahibi Muvafakatnamesi istenmiştir."},
                {"alan": "eksik belge", "deger": "Mülk Sahibi Muvafakatnamesi", "kaynak_satir": "Bu belgeyi henüz temin edemedim ve itiraz dilekçemin ekinde de sunamıyorum."},
            ],
            missing=[{"alan": "Mülk Sahibi Muvafakatnamesi", "neden": "Başvuran belgeyi henüz temin edemediğini ve sunamadığını bildirmiştir."}],
            questions=["Mülk Sahibi Muvafakatnamesini sunabilir misiniz?"],
            must_include=["Mülk Sahibi Muvafakatnamesini Müdürlüğümüze sunmanız gerekmektedir"],
            must_not_invent=["belgenin teslim tarihi", "mülk sahibinin adı", "başvurunun kabul edildiği"],
        ),
        _base(
            case_id="GKC-EKSIK_BELGE-002",
            decision="eksik_belge",
            institution="BURSA İL MİLLÎ EĞİTİM MÜDÜRLÜĞÜ",
            incoming="""T.C.
BURSA İL MİLLÎ EĞİTİM MÜDÜRLÜĞÜNE

Konu: 11.02.2026 tarihli denklik başvurusu bildirimine itiraz

Yurt dışında tamamladığım eğitime ilişkin diploma örneğini sundum. Ancak not dökümünün yeminli tercümesini henüz alamadığım için başvuruya ve bu itiraza ekleyemiyorum. Diploma örneği üzerinden denklik işleminin tamamlanmasını talep ediyorum.

16.02.2026
[KİŞİ ADI]
Başvuru No: [BAŞVURU NUMARASI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="Not dökümünün yeminli tercümesi olmadan denklik işleminin tamamlanması.",
            reason="Başvuran, not dökümünün yeminli tercümesini henüz alamadığını ve sunamadığını bildirmiştir. Eksik belge tamamlanmadan denklik dosyası sonuçlandırılamaz.",
            draft="""T.C.
BURSA İL MİLLÎ EĞİTİM MÜDÜRLÜĞÜ
Denklik Birimi

Sayı: E-2026/2481
Konu: Denklik Başvurusu Eksik Belge Bildirimi
Tarih: 20.02.2026

İlgi: 16.02.2026 tarihli itiraz dilekçeniz.

Denklik başvurunuz incelenmiştir. Dilekçenizde diploma örneğini sunduğunuzu, not dökümünün yeminli tercümesini ise henüz alamadığınız için başvuruya ekleyemediğinizi belirtmektesiniz.

Denklik dosyanızın sonuçlandırılabilmesi için not dökümünün yeminli tercümesini Müdürlüğümüze sunmanız gerekmektedir. Eksik belge sunulduğunda dosyanız yeniden değerlendirilecektir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
İl Millî Eğitim Müdürü""",
            facts=[
                {"alan": "eksik belge", "deger": "not dökümünün yeminli tercümesini", "kaynak_satir": "Ancak not dökümünün yeminli tercümesini henüz alamadığım için başvuruya ve bu itiraza ekleyemiyorum."}
            ],
            missing=[{"alan": "Not dökümünün yeminli tercümesi", "neden": "Başvuran belgeyi henüz alamadığını ve sunamadığını bildirmiştir."}],
            questions=["Not dökümünün yeminli tercümesini sunabilir misiniz?"],
            must_include=["not dökümünün yeminli tercümesini Müdürlüğümüze sunmanız gerekmektedir"],
            must_not_invent=["mezuniyet notu", "okul adı", "belgenin teslim tarihi"],
        ),
        _base(
            case_id="GKC-YETKISIZLIK-002",
            decision="yetkisizlik",
            institution="BURSA VALİLİĞİ",
            incoming="""T.C.
BURSA VALİLİĞİ
İl Ticaret Müdürlüğüne

Konu: 2026/445 sayılı emlak vergisi kaydına itiraz

Nilüfer ilçesindeki taşınmazım için Nilüfer Belediye Başkanlığı tarafından oluşturulan 2026/445 sayılı emlak vergisi kaydındaki kullanım türünün düzeltilmesini İl Ticaret Müdürlüğünüzden talep ediyorum. Kaydı oluşturan kurum Nilüfer Belediye Başkanlığıdır; buna rağmen işlemin Valilikçe iptal edilmesini istiyorum.

15.02.2026
[KİŞİ ADI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="Nilüfer Belediye Başkanlığınca oluşturulan emlak vergisi kaydının İl Ticaret Müdürlüğünce düzeltilmesi.",
            reason="İtiraz konusu 2026/445 sayılı emlak vergisi kaydı Nilüfer Belediye Başkanlığı tarafından oluşturulmuştur. İl Ticaret Müdürlüğünün belediye emlak vergisi kaydını düzeltme veya iptal etme yetkisi bulunmadığından başvuru yetkili belediye birimine yönlendirilmiştir.",
            draft="""T.C.
BURSA VALİLİĞİ
İl Ticaret Müdürlüğü

Sayı: E-2026/1908
Konu: Yetkili Mercie Yönlendirme
Tarih: 20.02.2026

İlgi: 15.02.2026 tarihli itiraz dilekçeniz.

İtirazınız, Nilüfer Belediye Başkanlığı tarafından oluşturulan 2026/445 sayılı emlak vergisi kaydındaki kullanım türünün düzeltilmesine ilişkindir.

İl Ticaret Müdürlüğünün belediye emlak vergisi kayıtlarını düzeltme veya iptal etme yetkisi bulunmamaktadır. Başvurunuz değerlendirilmek üzere yetkili merci olan NİLÜFER BELEDİYE BAŞKANLIĞI Mali Hizmetler Müdürlüğüne gönderilmiştir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
İl Ticaret Müdürü""",
            facts=[
                {"alan": "itiraz edilen kayıt", "deger": "2026/445", "kaynak_satir": "Nilüfer ilçesindeki taşınmazım için Nilüfer Belediye Başkanlığı tarafından oluşturulan 2026/445 sayılı emlak vergisi kaydındaki kullanım türünün düzeltilmesini İl Ticaret Müdürlüğünüzden talep ediyorum."}
            ],
            must_include=["NİLÜFER BELEDİYE BAŞKANLIĞI", "yetkisi bulunmamaktadır"],
            must_not_invent=["vergi tutarı", "taşınmaz adresi", "itirazın kabul edildiği"],
        ),
        _base(
            case_id="GKC-COKLU_TALEP-001",
            decision="coklu_talep",
            institution="ESHOT GENEL MÜDÜRLÜĞÜ",
            incoming="""T.C.
İZMİR BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI
ESHOT GENEL MÜDÜRLÜĞÜNE

Konu: Ulaşım kartı başvurusuna ilişkin çoklu talep ve itiraz

[BAŞVURU NUMARASI] numaralı ulaşım kartı başvurum portalda incelemede görünmektedir. Başvurumdaki e-posta adresinin [E-POSTA] olarak düzeltilmesini, mevcut başvuru durumunun yazılı olarak bildirilmesini ve başvurumun sırada öne alınmasını talep ediyorum. Sırada öncelik gerektiren bir acil durum belgesi sunmuyorum.

15.02.2026
[KİŞİ ADI]
Adres: [ADRES]
İmza: [KİŞİ ADI]""",
            requested_action="E-posta adresinin düzeltilmesi, başvuru durumunun bildirilmesi ve sırada öncelik verilmesi.",
            reason="E-posta düzeltme talebi kabul edilmiş, portalda incelemede görünen başvurunun mevcut durumu bildirilmiş, acil durum belgesi sunulmadığı için sırada öncelik talebi reddedilmiştir.",
            draft="""T.C.
İZMİR BÜYÜKŞEHİR BELEDİYE BAŞKANLIĞI
ESHOT GENEL MÜDÜRLÜĞÜ

Sayı: E-2026/3650
Konu: Ulaşım Kartı Başvurusu Hakkında
Tarih: 20.02.2026

İlgi: 15.02.2026 tarihli itiraz dilekçeniz.

[BAŞVURU NUMARASI] numaralı ulaşım kartı başvurunuza ilişkin üç talebiniz ayrı ayrı incelenmiştir.

1. Başvurunuzdaki e-posta adresinin [E-POSTA] olarak düzeltilmesi talebiniz kabul edilmiş ve iletişim kaydınız güncellenmiştir.
2. Başvurunuzun mevcut durumu incelemede olup bu bilgi tarafınıza bildirilmiştir.
3. Sırada öncelik gerektiren bir acil durum belgesi sunmadığınızı belirttiğinizden başvurunuzun sırada öne alınması talebiniz reddedilmiştir.

Bilgilerinize sunulur.

[İMZA SAHİBİ]
Kart İşlemleri Dairesi Başkanı""",
            facts=[
                {"alan": "başvuru numarası", "deger": "[BAŞVURU NUMARASI]", "kaynak_satir": "[BAŞVURU NUMARASI] numaralı ulaşım kartı başvurum portalda incelemede görünmektedir."},
                {"alan": "başvuru durumu", "deger": "incelemede", "kaynak_satir": "[BAŞVURU NUMARASI] numaralı ulaşım kartı başvurum portalda incelemede görünmektedir."},
            ],
            must_include=["talebiniz kabul edilmiş", "talebiniz reddedilmiştir", "mevcut durumu incelemede"],
            must_not_invent=["teslim tarihi", "kart numarası", "acil durum belgesinin var olduğu"],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    planned = curated_cases()
    existing = _load_existing_cases(MAIN_OUTPUT)
    existing_ids = {case["case_id"] for case in existing}
    additions = [case for case in planned if case["case_id"] not in existing_ids]
    print(json.dumps({"planned": len(planned), "new": len(additions)}, ensure_ascii=False))
    if args.apply and additions:
        _write_jsonl_atomic(MAIN_OUTPUT, [*existing, *additions])
        print(f"Checkpoint güncellendi: {len(existing) + len(additions)} vaka")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
